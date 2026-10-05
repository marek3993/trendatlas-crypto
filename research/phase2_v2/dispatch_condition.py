"""Cheap systemd ExecCondition: no market import and no empty broker ticks."""
import argparse
from pathlib import Path
import sqlite3

def executable(root=None, mailbox=None, fold_count=14):
    if mailbox is not None:
        mailbox=Path(mailbox)
        return any(not (mailbox/'responses'/p.name).exists() for p in (mailbox/'requests').glob('*.json'))
    path=Path(root)/'v2.sqlite'
    if not path.exists():return False
    db=sqlite3.connect('file:'+str(path)+'?mode=ro',uri=True)
    try:return db.execute('SELECT COUNT(*) FROM test_books').fetchone()[0]<fold_count
    finally:db.close()

if __name__=='__main__':
    p=argparse.ArgumentParser();g=p.add_mutually_exclusive_group(required=True)
    g.add_argument('--root',type=Path);g.add_argument('--mailbox',type=Path);p.add_argument('--fold-count',type=int,default=14)
    a=p.parse_args();raise SystemExit(0 if executable(a.root,a.mailbox,a.fold_count) else 1)
