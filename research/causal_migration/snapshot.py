"""Locked, SQLite-safe backup and immutable file manifest. No production access."""
import argparse
import datetime as dt
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent))
import runtime as r


def manifest(root):
    return {p.relative_to(root).as_posix():dict(bytes=p.stat().st_size,sha256=r.legacy.sha(p))
            for p in sorted(root.rglob('*')) if p.is_file() and p.name!='transfer_manifest.json'}


def snapshot(state, destination, engine=r.ENGINE):
    state=Path(state).resolve();destination=Path(destination).resolve()
    if destination.exists():raise FileExistsError(destination)
    if destination.is_relative_to(state):raise ValueError('Backup must be outside live state')
    r.legacy.verify(state,engine,r.POLICY);r.legacy.load_engine(engine)
    from research.causal_evolution.locking import WorkerLock
    with WorkerLock(state/'worker.lock'),WorkerLock(state/'mailbox/broker.lock'):
        destination.mkdir(parents=True)
        audit=dict(source=str(state),utc=dt.datetime.now(dt.timezone.utc).isoformat(),databases={})
        for name in ('candidates.sqlite','mailbox/proposals.sqlite'):
            target=destination/name;target.parent.mkdir(parents=True,exist_ok=True)
            source=r.legacy.readonly(state/name);dest=sqlite3.connect(target)
            try:
                source.backup(dest,pages=256,sleep=.01)
                if dest.execute('PRAGMA integrity_check').fetchall()!=[('ok',)] or dest.execute('PRAGMA foreign_key_check').fetchall():raise RuntimeError('Backup integrity')
                tables=[x[0] for x in dest.execute("SELECT name FROM sqlite_master WHERE type='table'")]
                audit['databases'][name]=dict(integrity='ok',foreign_keys=[],tables={t:dict(count=dest.execute('SELECT COUNT(*) FROM '+t).fetchone()[0],sha256=r.rows_hash(dest,t)) for t in tables})
            finally:dest.close();source.close()
            audit['databases'][name]['sha256']=r.legacy.sha(target)
        for path in state.rglob('*'):
            if path.is_symlink():raise RuntimeError('Unexpected state symlink')
            if not path.is_file() or path.name.endswith(('.sqlite','.sqlite-wal','.sqlite-shm','.lock')):continue
            if path.suffix not in ('.json','.csv','.svg','.md','.txt'):raise RuntimeError('Unexpected state file type: '+path.name)
            target=destination/path.relative_to(state);target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(path,target)
        r.atomic(destination/'backup_audit.json',audit)
        r.atomic(destination/'transfer_manifest.json',manifest(destination))
    return audit


def verify(root):
    root=Path(root)
    recorded=json.loads((root/'transfer_manifest.json').read_text())
    if manifest(root)!=recorded:raise RuntimeError('Transfer manifest mismatch')
    for name in ('candidates.sqlite','mailbox/proposals.sqlite'):
        d=r.legacy.readonly(root/name,immutable=True)
        try:
            if d.execute('PRAGMA integrity_check').fetchall()!=[('ok',)] or d.execute('PRAGMA foreign_key_check').fetchall():raise RuntimeError('Transferred SQLite integrity')
        finally:d.close()
    return dict(files=len(recorded),sha256=r.legacy.sha(root/'transfer_manifest.json'),integrity='ok')


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('command',choices=['backup','verify']);p.add_argument('--state',type=Path,default=r.STATE);p.add_argument('--destination',type=Path,required=True);p.add_argument('--engine',type=Path,default=r.ENGINE);a=p.parse_args()
    print(json.dumps(snapshot(a.state,a.destination,a.engine) if a.command=='backup' else verify(a.destination),sort_keys=True))
