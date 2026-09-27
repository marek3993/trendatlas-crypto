"""Resume-only orchestration for one immutable engine and experiment.

Kept OUTSIDE causal_evolution so its preregistered file fingerprint is unchanged.
No monkeypatching, new experiments, evaluator forks, or budget overrides.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import signal
import shutil
import sqlite3
import sys
import time

HERE = Path(__file__).resolve().parent
POLICY = json.loads((HERE / 'contract.json').read_text())
ENGINE = Path('/opt/trendatlas-research/releases') / POLICY['engine_commit']
STATE = Path('/var/lib/trendatlas-research/causal-v1/current')


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def readonly(path, immutable=False):
    # immutable is ONLY for closed backup-API copies, never a live WAL database.
    query = '?mode=ro' + ('&immutable=1' if immutable else '')
    return sqlite3.connect(Path(path).resolve().as_uri() + query, uri=True, timeout=10)


def metadata(db):
    return {k: json.loads(v) for k, v in db.execute('SELECT key,value FROM meta')}


def verify(state, engine, policy=POLICY):
    """Read-only, fail closed, BEFORE opening Store or touching reservations."""
    state, engine = Path(state).resolve(), Path(engine).resolve()
    manifest_path = state / 'frozen_manifest.json'
    if sha(manifest_path) != policy['manifest_sha256']:
        raise RuntimeError('Frozen manifest binding mismatch')
    manifest = json.loads(manifest_path.read_text())
    if (manifest['experiment_id'] != policy['experiment_id'] or
            manifest['fingerprint'] != policy['fingerprint']):
        raise RuntimeError('Frozen experiment binding mismatch')
    root = engine / 'research/causal_evolution'
    files = {p.relative_to(root).as_posix(): sha(p) for p in root.rglob('*')
             if p.is_file() and p.suffix in ('.py', '.json', '.zip')
             and not any(x in p.parts for x in ('local_state', '__pycache__', 'evidence'))}
    fingerprint = hashlib.sha256(json.dumps(files, sort_keys=True,
        separators=(',', ':'), allow_nan=False).encode()).hexdigest()
    if not files or files != manifest['files'] or fingerprint != policy['fingerprint']:
        raise RuntimeError('Frozen engine or raw inputs changed')
    db = readonly(state / 'candidates.sqlite')
    try:
        meta = metadata(db)
        if (meta.get('experiment_id') != policy['experiment_id'] or
                meta.get('fingerprint') != policy['fingerprint']):
            raise RuntimeError('SQLite experiment binding mismatch')
        if meta.get('outer_opened', False) and not meta.get('search_frozen', False):
            raise RuntimeError('Outer barrier invariant violated')
        if meta.get('search_frozen', False) and not (state / 'frozen_finalists.json').is_file():
            raise RuntimeError('Frozen nomination artifact missing')
    finally:
        db.close()
    if not (state / 'mailbox/proposals.sqlite').is_file():
        raise RuntimeError('Existing broker database required')
    return meta


def load_engine(engine):
    engine = Path(engine).resolve()
    sys.path.insert(0, str(engine))
    from research.causal_evolution import protocol
    if Path(protocol.__file__).resolve().parents[2] != engine:
        raise RuntimeError('Unexpected imported engine location')


def transition(store, status, reason, **extra):
    from research.causal_evolution.protocol import utc
    event = dict(utc=utc(), status=status, reason=reason,
                 experiment_id=store.meta('experiment_id'),
                 fingerprint=store.meta('fingerprint'), counts=store.counts(),
                 outer_opened=store.meta('outer_opened', False), **extra)
    with store.db:
        store.db.execute('CREATE TABLE IF NOT EXISTS orchestration_events '
                         '(id INTEGER PRIMARY KEY, body TEXT NOT NULL)')
        store.db.execute('INSERT INTO orchestration_events(body) VALUES(?)',
                         (json.dumps(event, sort_keys=True),))
        for key, value in (('status', status), ('pause_reason', reason)):
            store.db.execute('INSERT OR REPLACE INTO meta VALUES(?,?)',
                             (key, json.dumps(value)))
    # SQLite is authoritative even if atomic JSON export is interrupted.
    store.status(outer_opened=event['outer_opened'],
                 engine_commit=POLICY['engine_commit'], fingerprint=event['fingerprint'])


def reconcile(store):
    """Retain every attempt in the frozen budget; never delete cached results."""
    from research.causal_evolution.protocol import utc
    with store.db:
        store.db.execute('BEGIN IMMEDIATE')
        rows = store.db.execute("SELECT id,cache_key FROM attempts WHERE status='RUNNING'").fetchall()
        if len(rows) > 1:
            raise RuntimeError('More than one abandoned reservation')
        for row in rows:
            if store.db.execute('SELECT 1 FROM evaluations WHERE cache_key=?', (row[1],)).fetchone():
                raise RuntimeError('Completed result with RUNNING attempt violates atomic save')
            store.db.execute("UPDATE attempts SET status='INTERRUPTED',finished=? WHERE id=?",
                             (utc(), row[0]))
    return [row[0] for row in rows]


def search_loop(store, evaluator, guard, synthetic=False, inline_broker=False):
    from research.causal_evolution.controller import run_search, outer_estimate, AwaitBroker
    from research.causal_evolution.reporting import export
    while True:
        guard(force=True)
        try:
            run_search(store, evaluator, synthetic, inline_broker)
        except AwaitBroker:
            time.sleep(3)
            guard(force=True)  # Caught by activation's OUTER cooperative handler.
            continue
        guard(force=True)
        outer_estimate(store, evaluator, synthetic)
        export(store)
        return


def activate(store, seconds, pi=False, synthetic=False, inline_broker=False, stopped=None):
    from research.causal_evolution.resources import Guard, PauseResearch
    from research.causal_evolution.evaluator import Evaluator
    from research.causal_evolution.protocol import utc
    if store.meta('status') == 'SEALED':
        return 0
    if store.meta('status') not in POLICY['resumable_states']:
        raise RuntimeError('State is not admitted for resume')
    guard = Guard(store, pi=pi, seconds=seconds)
    if stopped and stopped[0]:
        guard.request_stop()
    try:
        interrupted = reconcile(store)
        transition(store, 'RUNNING', None, interrupted_attempts=interrupted)
        search_loop(store, Evaluator(store, synthetic=synthetic, guard=guard), guard,
                    synthetic, inline_broker)
        return 0
    except PauseResearch as exc:
        interrupted = reconcile(store)
        reason = str(exc)
        transition(store, 'CHECKPOINTED' if reason == 'bounded_activation_checkpoint'
                   else 'PAUSED_WAITING_RESUME', reason, interrupted_attempts=interrupted)
        return 0
    except Exception as exc:
        store.set('failure', dict(type=type(exc).__name__, reason=str(exc)[:500], utc=utc()))
        transition(store, 'FAILED', 'runtime_error')
        raise
    finally:
        # Include imports, cached work and final checkpoint time in the OLD budget.
        store.set('active_seconds', max(float(store.meta('active_seconds', 0)),
                  guard.prior + time.monotonic() - guard.start))


def recover(store, backup, policy=POLICY):
    """One explicit repair of the evidenced legacy misclassification, idempotent."""
    if store.meta('orchestration_recovery'):
        return
    backup = Path(backup).resolve()
    audit = json.loads((backup / 'backup_audit.json').read_text())
    if Path(audit['source']).resolve() != store.root.resolve():
        raise RuntimeError('Backup source mismatch')
    if sha(backup / 'frozen_manifest.json') != policy['manifest_sha256']:
        raise RuntimeError('Backup manifest mismatch')
    for name in ('candidates.sqlite', 'mailbox/proposals.sqlite'):
        if sha(backup / name) != audit['databases'][name]['sha256']:
            raise RuntimeError('Backup checksum mismatch')
        db = readonly(backup / name, immutable=True)
        try:
            if db.execute('PRAGMA integrity_check').fetchall() != [('ok',)]:
                raise RuntimeError('Backup integrity failure')
        finally:
            db.close()
    old = readonly(backup / 'candidates.sqlite', immutable=True)
    try:
        with store.db:
            store.db.execute('BEGIN IMMEDIATE')
            failure = store.meta('failure', {})
            if (store.meta('status') != 'FAILED' or failure.get('type') != policy['recovery']['failure_type']
                    or failure.get('reason') != policy['recovery']['failure_reason']
                    or store.meta('outer_opened', False)):
                raise RuntimeError('Not the approved legacy checkpoint failure')
            if store.counts()['evaluations'] != policy['recovery']['completed_evaluations']:
                raise RuntimeError('Unexpected completed count before recovery')
            for table in ('evaluations', 'attempts', 'trials', 'populations', 'scores', 'candidates', 'finalists'):
                # Full row comparison includes compressed payloads and lineage.
                if sorted(map(tuple, store.db.execute('SELECT * FROM '+table))) != sorted(old.execute('SELECT * FROM '+table)):
                    raise RuntimeError('Live state differs from verified backup: '+table)
            record = dict(backup=str(backup), legacy_failure=failure,
                          retained_evaluations=store.counts()['evaluations'])
            for key, value in (('orchestration_recovery', record), ('failure', None),
                               ('status', 'CHECKPOINTED'), ('pause_reason', 'bounded_activation_checkpoint')):
                store.db.execute('INSERT OR REPLACE INTO meta VALUES(?,?)', (key, json.dumps(value)))
    finally:
        old.close()
    transition(store, 'CHECKPOINTED', 'bounded_activation_checkpoint', recovery=True)


def ready(meta):
    if meta.get('status') not in POLICY['resumable_states']:
        return 255  # MUST suppress dispatcher OnSuccess; terminal failures stay failures.
    # SQLite, not a possibly stale status.json, controls admission after a crash.
    from research.causal_evolution.protocol import CONTRACT
    thermal = list(Path('/sys/class/thermal').glob('thermal_zone*/temp'))
    if not thermal or max(int(p.read_text())/1000 for p in thermal) >= CONTRACT['runtime']['thermal_resume_c']:
        return 255
    if shutil.disk_usage(STATE).free < CONTRACT['runtime']['disk_free_reserve_mib']*1024**2:
        return 255
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=['ready', 'run', 'recover'])
    parser.add_argument('--backup')
    parser.add_argument('--seconds', type=int, default=POLICY['cooperative_seconds'])
    args = parser.parse_args(argv)
    if not 0 < args.seconds <= POLICY['cooperative_seconds']:
        raise ValueError('Activation can only shorten the frozen time allowance')
    stopped = [False]
    signal.signal(signal.SIGTERM, lambda *_: stopped.__setitem__(0, True))
    signal.signal(signal.SIGINT, lambda *_: stopped.__setitem__(0, True))
    for key in ('OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS', 'MKL_NUM_THREADS', 'NUMEXPR_NUM_THREADS'):
        os.environ[key] = '1'
    meta = verify(STATE, ENGINE)
    load_engine(ENGINE)
    if args.command == 'ready':
        return ready(meta)
    from research.causal_evolution.locking import WorkerLock
    from research.causal_evolution.store import Store
    from research.causal_evolution.resources import lock_memory
    with WorkerLock(STATE / 'worker.lock'):
        verify(STATE, ENGINE)
        store = Store(STATE.resolve())
        try:
            if args.command == 'recover':
                if not args.backup:
                    raise ValueError('Verified backup required')
                recover(store, args.backup)
                return 0
            lock_memory()
            return activate(store, args.seconds, pi=True, stopped=stopped)
        finally:
            store.close()


def entrypoint(argv=None):
    args = sys.argv[1:] if argv is None else argv
    try:
        return main(args)
    except Exception:
        if args and args[0] == 'ready':
            # systemd treats ExecCondition exit 1..254 as a successful SKIP and
            # can still trigger OnSuccess. Admission errors MUST return 255.
            print('Research admission failed closed', file=sys.stderr)
            return 255
        raise


if __name__ == '__main__':
    raise SystemExit(entrypoint())
