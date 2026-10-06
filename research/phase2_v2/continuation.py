"""Resume the frozen evaluator; terminal books never become fabricated equity."""
import argparse
from concurrent.futures import ProcessPoolExecutor
import json
from pathlib import Path
import sqlite3
import sys
import time

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from research.phase2_v2 import runtime as r


def policy():
    p = Path(__file__).resolve().parents[2] / 'source_of_truth/phase2_v2_recovery_contract.json'
    c = json.loads(p.read_text())
    assert c['base_contract'] == 'phase2_v2_contract.json'
    assert not any(c[k] for k in ('production_writes_allowed', 'orders_allowed', 'sealed_data_access_allowed'))
    return c


def initialize(db):
    c = policy()
    db.executescript('''
    CREATE TABLE IF NOT EXISTS terminal_test_failures(origin INTEGER PRIMARY KEY,
      receipt TEXT NOT NULL, finished TEXT NOT NULL);
    CREATE TRIGGER IF NOT EXISTS terminal_test_no_update BEFORE UPDATE ON terminal_test_failures
      BEGIN SELECT RAISE(ABORT,'immutable_terminal_test'); END;
    CREATE TRIGGER IF NOT EXISTS terminal_test_no_delete BEFORE DELETE ON terminal_test_failures
      BEGIN SELECT RAISE(ABORT,'immutable_terminal_test'); END;
    ''')
    binding = r.digest([c, Path(__file__).read_bytes().hex()])
    old = db.execute("SELECT value FROM meta WHERE key='continuation_binding'").fetchone()
    if old:
        if json.loads(old[0]) != binding:
            raise RuntimeError('continuation_binding_changed')
    else:
        with db:
            db.execute("INSERT INTO meta VALUES('continuation_binding',?)", (r.canonical(binding),))
            r.event(db, 'terminal_book_continuation_bound', binding=binding, policy=c['id'],
                    evaluator_and_inputs_unchanged=True)


def processed(db):
    ids = [x[0] for x in db.execute('SELECT origin FROM test_books UNION SELECT origin FROM terminal_test_failures ORDER BY origin')]
    if ids != list(range(len(ids))):
        raise RuntimeError('processed_origin_gap')
    if db.execute('SELECT origin FROM test_books INTERSECT SELECT origin FROM terminal_test_failures').fetchone():
        raise RuntimeError('duplicate_test_outcome')
    return len(ids)


def test_selected(db, origin, market):
    if db.execute('SELECT 1 FROM terminal_test_failures WHERE origin=?', (origin,)).fetchone():
        return
    if db.execute('SELECT 1 FROM test_books WHERE origin=?', (origin,)).fetchone():
        return
    selection = db.execute('SELECT candidate_id,genes,evidence,frozen_utc FROM selections WHERE origin=?', (origin,)).fetchone()
    if selection is None:
        raise RuntimeError('test_before_selection_freeze')
    prior = db.execute('SELECT origin,receipt FROM terminal_test_failures ORDER BY origin LIMIT 1').fetchone()
    previous = db.execute('SELECT result FROM test_books WHERE origin=?', (origin-1,)).fetchone()
    if prior:
        reason = json.loads(prior[1])['reason']
        state = 'NOT_EVALUABLE_CONTINUITY_LOST'
    else:
        try:
            r.test_selected(db, origin, market)
            return
        except ValueError as exc:
            reason = str(exc)
            if not any(reason.startswith(prefix) for prefix in policy()['terminal_errors']):
                raise
            state = 'UNDEFINED_INVALID'
    receipt = {'state': state, 'reason': reason, 'origin': origin,
               'first_invalid_origin': prior[0] if prior else origin,
               'selection_id': selection[0], 'selection_sha256': r.digest(list(selection)),
               'selection_frozen_utc': selection[3],
               'previous_book_sha256': r.digest(json.loads(previous[0])) if previous else None,
               'continuous_portfolio_valid': False, 'full_horizon_cagr': None,
               'liquidation_or_cash_reset': False}
    with db:
        db.execute('INSERT INTO terminal_test_failures VALUES(?,?,?)', (origin, r.canonical(receipt), r.utc()))
        r.event(db, 'development_test_terminal_invalid', **receipt)


def status(db):
    result = r.status(db)
    done = processed(db)
    failure = db.execute('SELECT origin,receipt,finished FROM terminal_test_failures ORDER BY origin LIMIT 1').fetchone()
    result.update(active_evolution=done < len(r.C['walk_forward']['validation_folds']),
                  processed_origins=done, invalid_test_folds=done-result['test_folds_completed'],
                  checkpoint_utc=db.execute('SELECT MAX(utc) FROM events').fetchone()[0],
                  research_failure=json.loads(failure[1]) if failure else None,
                  continuous_portfolio_valid=not bool(failure),
                  continuous_portfolio_cagr=None if failure else 'SEE_VALID_BOOK_AUDIT')
    return result


def executable(root):
    db = sqlite3.connect('file:' + str(Path(root)/'v2.sqlite') + '?mode=ro', uri=True)
    try:
        if not db.execute("SELECT 1 FROM sqlite_master WHERE name='terminal_test_failures'").fetchone():
            return db.execute('SELECT COUNT(*) FROM test_books').fetchone()[0] < 14
        return processed(db) < 14
    finally:
        db.close()


def run(root, inputs, workers=2, seconds=240):
    import fcntl
    r.validate(r.C, activate=True)
    root = Path(root)
    with (root/'runner.lock').open('a+') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        db = r.connect(root)
        try:
            bindings = r.binding(inputs)
            r.initialize(db, bindings)  # Exact frozen evaluator binding; never migrated.
            initialize(db)
            if not (root/'references/summary.json').exists():
                raise RuntimeError('references_must_complete_before_evolution')
            market = r.load_market(Path(inputs))
            r.init_worker(market)
            deadline = time.monotonic()+seconds
            with ProcessPoolExecutor(max_workers=workers, initializer=r.init_worker, initargs=(market,)) as pool:
                while time.monotonic() < deadline:
                    origin = processed(db)
                    if origin >= len(r.C['walk_forward']['validation_folds']):
                        break
                    r.seed(db, origin)
                    gen = db.execute('SELECT MAX(generation) FROM members WHERE origin=?', (origin,)).fetchone()[0]
                    tasks = r.pending(db, origin, gen, bindings)
                    if tasks:
                        for result in pool.map(r.job, tasks[:workers]):
                            r.store_job(db, bindings, result)
                        r.atomic(root/'status.json', status(db))
                        continue
                    state = r.advance(db, root, origin, gen)
                    r.atomic(root/'quality.json', r.quality(db, origin))
                    if state == 'FROZEN':
                        test_selected(db, origin, market)
                    r.atomic(root/'status.json', status(db))
                    if state == 'WAITING':
                        break
            return status(db)
        finally:
            db.close()


def main():
    p = argparse.ArgumentParser()
    p.add_argument('command', choices=['run', 'condition', 'status'])
    p.add_argument('--root', type=Path, required=True)
    p.add_argument('--inputs', type=Path)
    p.add_argument('--workers', type=int, choices=[1, 2], default=2)
    p.add_argument('--seconds', type=int, default=240)
    a = p.parse_args()
    if a.command == 'condition':
        raise SystemExit(0 if executable(a.root) else 1)
    if a.command == 'run':
        print(r.canonical(run(a.root, a.inputs, a.workers, a.seconds)))
    else:
        db = sqlite3.connect('file:'+str(a.root/'v2.sqlite')+'?mode=ro', uri=True)
        try:
            print(r.canonical(status(db)))
        finally:
            db.close()


if __name__ == '__main__':
    main()
