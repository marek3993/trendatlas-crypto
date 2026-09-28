"""Evidence-bound recovery and host-neutral orchestration; frozen engine untouched."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import secrets
import signal
import sqlite3
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent
POLICY = json.loads((HERE / 'contract.json').read_text())
spec = importlib.util.spec_from_file_location('legacy_resume', HERE.parent / 'causal_resume/runtime.py')
legacy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(legacy)
ENGINE = Path('/opt/trendatlas-research/releases') / POLICY['engine_commit']
STATE = Path('/var/lib/trendatlas-research/causal-v1/current')
TABLES = ('evaluations', 'attempts', 'candidates', 'trials', 'populations', 'scores', 'finalists')


def atomic(path, value):
    path = Path(path)
    temporary = path.with_name(path.name + '.tmp.' + str(os.getpid()))
    with temporary.open('w') as f:
        json.dump(value, f, sort_keys=True, allow_nan=False)
        f.flush()
        os.fsync(f.fileno())
    os.replace(temporary, path)


def rows_hash(db, table):
    columns = db.execute('PRAGMA table_info(' + table + ')').fetchall()
    keys = [c[1] for c in sorted(columns, key=lambda c: c[5]) if c[5]]
    order = ','.join(keys or [c[1] for c in columns])
    h = hashlib.sha256()
    for row in db.execute('SELECT * FROM ' + table + ' ORDER BY ' + order):
        for value in row:
            b = value if isinstance(value, bytes) else json.dumps(value, sort_keys=True).encode()
            h.update(len(b).to_bytes(8, 'big')); h.update(b)
    return h.hexdigest()


def validate_checkpoint(store, minimum=1, closed_outer=False, allow_running=False):
    """Validate the atomic result/attempt/checkpoint relationship, not just JSON."""
    for db in (store.db, store.mail):
        if [tuple(x) for x in db.execute('PRAGMA integrity_check')] != [('ok',)]:
            raise RuntimeError('SQLite integrity failed')
        if db.execute('PRAGMA foreign_key_check').fetchall():
            raise RuntimeError('SQLite foreign keys failed')
    count = store.db.execute('SELECT COUNT(*) FROM evaluations').fetchone()[0]
    if count < minimum:
        raise RuntimeError('Completed evaluation count regressed or checkpoint absent')
    missing = store.db.execute("SELECT e.cache_key FROM evaluations e LEFT JOIN attempts a ON a.cache_key=e.cache_key AND a.status='COMPLETE' GROUP BY e.cache_key HAVING COUNT(a.id)!=1 LIMIT 1").fetchone()
    extra = store.db.execute("SELECT a.id FROM attempts a LEFT JOIN evaluations e ON e.cache_key=a.cache_key WHERE a.status='COMPLETE' AND e.cache_key IS NULL LIMIT 1").fetchone()
    if missing or extra:
        raise RuntimeError('Atomic COMPLETE/evaluation bijection failed')
    cp = store.meta('checkpoint')
    if not cp:
        raise RuntimeError('No durable checkpoint')
    last = store.db.execute("SELECT id,cache_key,finished FROM attempts WHERE status='COMPLETE' ORDER BY id DESC LIMIT 1").fetchone()
    if not last or cp['attempt'] != last[0] or cp['evaluation'] != last[1]:
        raise RuntimeError('Last atomic checkpoint mismatch')
    running = store.db.execute("SELECT COUNT(*) FROM attempts WHERE status='RUNNING'").fetchone()[0]
    if running > (1 if allow_running else 0):
        raise RuntimeError('Open reservations remain')
    if store.db.execute("SELECT COUNT(*) FROM attempts WHERE status NOT IN ('RUNNING','COMPLETE','INTERRUPTED')").fetchone()[0]:
        raise RuntimeError('Unknown reservation status')
    if closed_outer and (store.meta('outer_opened', False) or store.db.execute("SELECT COUNT(*) FROM attempts WHERE scope='outer'").fetchone()[0]):
        raise RuntimeError('Outer must remain closed')
    if store.meta('outer_opened', False) and not store.meta('search_frozen', False):
        raise RuntimeError('Outer barrier violated')
    return dict(evaluations=count, checkpoint=cp, running=running,
                outer_opened=store.meta('outer_opened', False))


def event(store, status, reason, **fields):
    legacy.transition(store, status, reason, **fields)


def fail(store, error):
    from research.causal_evolution.protocol import utc
    failure = dict(type=type(error).__name__, reason=str(error)[:500], utc=utc())
    store.set('failure', failure)
    event(store, 'FAILED', 'orchestration_error', failure=failure)


def checkpoint(store, reason, minimum, closed_outer=False, **fields):
    # Validate first with one permitted abandoned reservation, then reconcile it.
    try:
        validate_checkpoint(store, minimum, closed_outer, allow_running=True)
        interrupted = legacy.reconcile(store)
        verified = validate_checkpoint(store, minimum, closed_outer)
    except Exception as exc:
        fail(store,exc)
        raise
    event(store, 'CHECKPOINTED', reason, verified=verified,
          interrupted_attempts=interrupted, **fields)
    return verified


def recover(store, backup, policy=POLICY):
    if store.meta('migration_recovery'):
        validate_checkpoint(store, policy['recovery']['completed_evaluations'], True)
        return
    backup = Path(backup)
    audit = json.loads((backup / 'backup_audit.json').read_text())
    if Path(audit['source']).resolve() != store.root.resolve():
        raise RuntimeError('Backup source mismatch')
    if legacy.sha(backup / 'frozen_manifest.json') != policy['manifest_sha256']:
        raise RuntimeError('Backup manifest mismatch')
    rule = policy['recovery']
    failure = store.meta('failure')
    if store.meta('status') != 'FAILED' or failure != dict(type=rule['failure_type'], reason=rule['failure_reason'], utc=rule['failure_utc']):
        raise RuntimeError('Not the authorized forensic failure')
    for t in ('evaluations','attempts','candidates','trials'):
        expected = rule['completed_evaluations'] if t == 'evaluations' else rule[t]
        if store.db.execute('SELECT COUNT(*) FROM ' + t).fetchone()[0] != expected:
            raise RuntimeError('Recovery count mismatch: ' + t)
    validate_checkpoint(store, rule['completed_evaluations'], True)
    for name, live, tables in (('candidates.sqlite',store.db,TABLES + ('meta','orchestration_events')),
                               ('mailbox/proposals.sqlite',store.mail,('proposals',))):
        if legacy.sha(backup / name) != audit['databases'][name]['sha256']:
            raise RuntimeError('Backup checksum mismatch')
        old = legacy.readonly(backup / name, immutable=True)
        try:
            if old.execute('PRAGMA integrity_check').fetchall() != [('ok',)] or old.execute('PRAGMA foreign_key_check').fetchall():
                raise RuntimeError('Backup integrity failed')
            for table in tables:
                if rows_hash(old, table) != rows_hash(live, table):
                    raise RuntimeError('Backup/live mismatch: ' + table)
        finally:
            old.close()
    from research.causal_evolution.protocol import utc
    record = dict(utc=utc(), authorization=rule['authorization'], original_failure=failure,
                  preserved_evaluations=rule['completed_evaluations'], backup=str(backup),
                  preserved={t:rows_hash(store.db,t) for t in TABLES}, ai_ledger_sha256=rows_hash(store.mail,'proposals'))
    with store.db:
        store.db.execute('INSERT INTO orchestration_events(body) VALUES(?)',
                         (json.dumps(dict(status='AUTHORIZED_RECOVERY', **record),sort_keys=True),))
        for key, value in (('migration_recovery',record),('failure',None),('status','CHECKPOINTED'),('pause_reason','authorized_sigterm_recovery')):
            store.db.execute('INSERT OR REPLACE INTO meta VALUES(?,?)',(key,json.dumps(value,sort_keys=True)))
    event(store, 'CHECKPOINTED', 'authorized_sigterm_recovery', preserved_evaluations=rule['completed_evaluations'])


class UnexpectedStop(RuntimeError):
    pass


class RunGuard:
    def __init__(self, store, seconds, pi, maximum, record):
        from research.causal_evolution.resources import Guard
        self.inner = Guard(store, seconds=seconds, pi=pi)
        self.store, self.maximum, self.record = store, maximum, record
        self.initial = store.counts()['evaluations']
        self.signalled = False
        self.previous = {s:signal.getsignal(s) for s in (signal.SIGTERM,signal.SIGINT)}
        for sig in self.previous:
            signal.signal(sig, self.signal)

    def signal(self, *_):
        self.signalled = True
        self.inner.request_stop()

    def expected(self):
        try:
            request = json.loads((self.store.root/'stop_request.json').read_text())
            return request['token'] == self.record['token'] and request['pid'] == self.record['pid']
        except (OSError, ValueError, KeyError):
            return False

    def __call__(self, force=False):
        from research.causal_evolution.resources import PauseResearch
        if self.signalled and not self.expected():
            raise UnexpectedStop('SIGTERM/SIGINT without bound administrative request')
        if self.maximum and self.store.counts()['evaluations'] >= self.initial + self.maximum:
            raise PauseResearch('validation_evaluation_limit')
        self.inner(force=force)

    def close(self):
        for sig, handler in self.previous.items():
            signal.signal(sig,handler)


def activate(store, seconds=1680, pi=False, synthetic=False, maximum=0, no_outer=False, loop=None):
    from research.causal_evolution.evaluator import Evaluator
    from research.causal_evolution.resources import PauseResearch
    from research.causal_evolution.protocol import utc
    if store.meta('status') not in legacy.POLICY['resumable_states']:
        raise RuntimeError('State not admitted')
    initial = store.counts()['evaluations']
    validate_checkpoint(store, max(1,initial), no_outer, allow_running=True)
    legacy.reconcile(store)
    record = dict(token=secrets.token_hex(16), pid=os.getpid(), utc=utc(),
                  initial_evaluations=initial, closed_outer=no_outer,
                  active_seconds_before=float(store.meta('active_seconds',0)), monotonic=time.monotonic())
    atomic(store.root/'activation.json',record)
    guard = RunGuard(store,seconds,pi,maximum,record)
    try:
        event(store,'RUNNING',None,activation=record)
        evaluator = Evaluator(store,synthetic=synthetic,guard=guard)
        if loop:
            loop(store,evaluator,guard)
        else:
            from research.causal_evolution.controller import run_search, outer_estimate, AwaitBroker
            from research.causal_evolution.reporting import export
            while True:
                guard(force=True)
                try:
                    run_search(store,evaluator,synthetic,False)
                except AwaitBroker:
                    time.sleep(1); continue
                guard(force=True)
                if no_outer:
                    raise PauseResearch('validation_outer_barrier')
                outer_estimate(store,evaluator,synthetic)
                export(store)
                break
        return 0
    except PauseResearch as exc:
        checkpoint(store,str(exc),max(1,initial),no_outer,activation_token=record['token'])
        return 0
    except subprocess.CalledProcessError as exc:
        if (guard.signalled and guard.expected() and exc.returncode == -signal.SIGTERM
                and list(exc.cmd) == ['/usr/bin/systemctl','list-jobs','--no-legend','--no-pager']):
            checkpoint(store,'administrative_helper_sigterm',max(1,initial),no_outer,
                       activation_token=record['token'], helper_signal='SIGTERM')
            return 0
        fail(store,exc); raise
    except Exception as exc:
        fail(store,exc); raise
    finally:
        store.set('active_seconds',max(float(store.meta('active_seconds',0)),
                  guard.inner.prior + time.monotonic()-guard.inner.start))
        guard.close()


def request_stop(state):
    state = Path(state)
    if not (state/'activation.json').exists():
        return
    record = json.loads((state/'activation.json').read_text())
    # Bound to this service's current PID; stale activation cannot signal another process.
    main_pid = os.environ.get('MAINPID')
    if not main_pid or int(main_pid) != record['pid']:
        return
    atomic(state/'stop_request.json',dict(token=record['token'],pid=record['pid'],reason='systemd_ExecStop'))
    try:os.kill(record['pid'],signal.SIGTERM)
    except ProcessLookupError:return
    deadline=time.monotonic()+90
    while time.monotonic()<deadline:
        try:os.kill(record['pid'],0)
        except ProcessLookupError:return
        time.sleep(.2)


def finalize(store, result):
    record=json.loads((store.root/'activation.json').read_text())
    if store.meta('status') in ('CHECKPOINTED','SEALED'):
        return
    if result != 'timeout':
        if store.meta('status') != 'FAILED':
            fail(store,UnexpectedStop('Unexpected service exit: '+result))
        return
    try:
        if store.meta('status') != 'RUNNING':
            raise RuntimeError('Timeout cannot reopen terminal state')
        store.set('active_seconds',max(float(store.meta('active_seconds',0)),
            record['active_seconds_before']+max(0,time.monotonic()-record['monotonic'])))
        checkpoint(store,'systemd_hard_timeout_verified',record['initial_evaluations'],
                   record['closed_outer'],activation_token=record['token'],service_result='timeout')
    except Exception as exc:
        fail(store,exc);raise


def main():
    p=argparse.ArgumentParser()
    p.add_argument('command',choices=['ready','run','stop','finalize','recover','inspect'])
    p.add_argument('--state',type=Path,default=STATE)
    p.add_argument('--engine',type=Path,default=ENGINE)
    p.add_argument('--platform',choices=['pi','vps'],default='pi')
    p.add_argument('--seconds',type=int,default=POLICY['cooperative_seconds'])
    p.add_argument('--max-evaluations',type=int,default=0)
    p.add_argument('--no-outer',action='store_true')
    p.add_argument('--backup',type=Path)
    a=p.parse_args()
    if not 0<a.seconds<=POLICY['cooperative_seconds'] or a.max_evaluations<0:
        raise ValueError('Invalid bounded activation')
    if not a.state.resolve().is_relative_to(Path('/var/lib/trendatlas-research')):
        raise ValueError('State must be research-only')
    for key in ('OPENBLAS_NUM_THREADS','OMP_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS'):
        os.environ[key]='1'
    meta=legacy.verify(a.state,a.engine,POLICY)
    if a.command=='stop':request_stop(a.state);return 0
    if a.command=='ready':
        if meta.get('status') not in legacy.POLICY['resumable_states']:return 255
        legacy.load_engine(a.engine)
        return legacy.ready(meta) if a.platform=='pi' else 0
    legacy.load_engine(a.engine)
    from research.causal_evolution.locking import WorkerLock
    from research.causal_evolution.store import Store
    with WorkerLock(a.state/'worker.lock'):
        legacy.verify(a.state,a.engine,POLICY)
        store=Store(a.state.resolve())
        try:
            if a.command=='recover':recover(store,a.backup)
            elif a.command=='finalize':finalize(store,os.environ.get('SERVICE_RESULT','unknown'))
            elif a.command=='inspect':print(json.dumps(validate_checkpoint(store,1,False),sort_keys=True))
            else:
                if a.platform=='pi':
                    from research.causal_evolution.resources import lock_memory
                    lock_memory()
                return activate(store,a.seconds,pi=a.platform=='pi',maximum=a.max_evaluations,no_outer=a.no_outer)
        finally:store.close()
    return 0


if __name__=='__main__':
    try:raise SystemExit(main())
    except Exception:
        if len(sys.argv)>1 and sys.argv[1]=='ready':raise SystemExit(255)
        raise
