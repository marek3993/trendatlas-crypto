"""One-time authorized legacy retirement, after both services have drained."""
import hashlib
import json
import shutil
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path('/var/lib/trendatlas-research-development')
RELEASE = Path('/opt/trendatlas-research/phase2-development/current')
sys.path.insert(0, str(RELEASE))
from research.phase2_continuous.runtime import event, verify_chain, atomic

def fingerprint_rows(db, table, columns):
    value = hashlib.sha256()
    for row in db.execute(f'SELECT {columns} FROM {table} ORDER BY 1'):
        value.update(json.dumps(row, separators=(',', ':'), ensure_ascii=True).encode())
        value.update(b'\n')
    return value.hexdigest()

def main():
    for name in ('development', 'broker'):
        for suffix in ('service', 'timer'):
            unit = f'trendatlas-phase2-{name}.{suffix}'
            state = subprocess.run(['systemctl', 'is-active', unit], capture_output=True, text=True).stdout.strip()
            if state not in ('inactive', 'failed'):
                raise RuntimeError('legacy_not_drained:' + unit + ':' + state)
    db = sqlite3.connect(ROOT / 'research.sqlite')
    verify_chain(db)
    previous = db.execute("SELECT body FROM events WHERE kind='methodology_retired' ORDER BY id DESC LIMIT 1").fetchone()
    if previous:
        print(previous[0])
        return
    if db.execute("SELECT count(*) FROM evaluations WHERE status IN ('RUNNING','PENDING')").fetchone()[0]:
        raise RuntimeError('unfinished_evaluations_require_recovery')
    count = db.execute('SELECT count(*) FROM candidates').fetchone()[0]
    evaluations = db.execute('SELECT status,count(*) FROM evaluations GROUP BY status').fetchall()
    row_hash = fingerprint_rows(db, 'evaluations', '*')
    candidate_hash = fingerprint_rows(db, 'candidates', '*')
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    checkpoint = ROOT / 'legacy-checkpoints' / stamp
    checkpoint.mkdir(parents=True, exist_ok=False)
    if shutil.disk_usage(ROOT).free < (ROOT/'research.sqlite').stat().st_size + 2*1024**3:
        raise RuntimeError('insufficient_checkpoint_disk')
    backup = sqlite3.connect(checkpoint / 'research.sqlite')
    db.backup(backup)
    if backup.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
        raise RuntimeError('backup_integrity')
    if fingerprint_rows(backup, 'evaluations', '*') != row_hash:
        raise RuntimeError('backup_results_differ')
    backup.close()
    cycle = db.execute('SELECT id,status,generation FROM cycles ORDER BY ordinal DESC LIMIT 1').fetchone()
    best = db.execute('SELECT id,genes,cycle_id,parent,mutation FROM candidates WHERE id=?',
        ('53e35c0943230832c56c97f57a07ff6e70caf3ae3aebe9db73d95ab8e4d6c87e',)).fetchone()
    receipt = dict(utc=datetime.now(timezone.utc).isoformat(), cycle_before=cycle,
        checkpoint=str(checkpoint), candidates=count, evaluations=evaluations,
        evaluation_rows_sha256=row_hash, candidate_rows_sha256=candidate_hash,
        old_best=best, classification='LEGACY_METHODOLOGICALLY_INCOMPARABLE',
        reason='arithmetic_mean_short_fold_annualized_CAGR_disconnected_books_null_concentration_coercion',
        completed_results_preserved=True, paid_legacy_mutations_disabled=True,
        production_touched=False, outer_oos='LOCKED', forward_2027='SEALED')
    with db:
        db.execute("UPDATE cycles SET status='LEGACY_METHODOLOGICALLY_INCOMPARABLE' WHERE id=?", (cycle[0],))
        db.execute("INSERT INTO meta VALUES('methodology_retired',?)", (json.dumps(receipt),))
        event(db, 'methodology_retired', **receipt)
    if fingerprint_rows(db, 'evaluations', '*') != row_hash or fingerprint_rows(db, 'candidates', '*') != candidate_hash:
        raise RuntimeError('preservation_check_failed')
    verify_chain(db)
    atomic(checkpoint/'receipt.json', receipt)
    atomic(ROOT/'legacy-retirement.json', receipt)
    atomic(ROOT/'status.json', dict(active_evolution=False, cycle=[cycle[0],receipt['classification'],cycle[2]],
        evaluation_counts=dict(evaluations), outer_oos='LOCKED', forward_2027='SEALED', checkpoint=str(checkpoint)))
    print(json.dumps(receipt))

if __name__ == '__main__':
    main()
