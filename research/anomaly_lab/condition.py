"""Stdlib-only dispatch guard: no arrays, credential or input reads on idle ticks."""
import argparse
import sqlite3
from pathlib import Path


def ready(root=None, mailbox=None, origins=14):
    if mailbox:
        mailbox = Path(mailbox)
        return any(not (mailbox/'responses'/p.name).exists() for p in (mailbox/'requests').glob('*.json'))
    path = Path(root)/'lab.sqlite'
    if not path.exists(): return True
    db = sqlite3.connect('file:'+path.as_posix()+'?mode=ro', uri=True)
    try: return db.execute('SELECT COUNT(*) FROM origins').fetchone()[0] < origins
    finally: db.close()


if __name__ == '__main__':
    p = argparse.ArgumentParser(); p.add_argument('--root', type=Path); p.add_argument('--mailbox', type=Path)
    a = p.parse_args(); raise SystemExit(0 if ready(a.root, a.mailbox) else 1)
