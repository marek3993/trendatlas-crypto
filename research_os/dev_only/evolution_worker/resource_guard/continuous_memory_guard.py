"""Pinned release-local memory/no-swap guard for continuous research only."""
import ctypes
import json
import os
from pathlib import Path
import runpy
import sqlite3
import sys

CAP = 384 * 1024 * 1024
RELEASE = Path(__file__).absolute().parents[1]
BOOTSTRAP = RELEASE / 'research_os/dev_only/evolution_worker/bootstrap.py'
STATE = Path('/var/lib/trendatlas-research')


def recover_interrupted_sqlite(state=STATE):
    """SQLite alone rolls back hot journals; SEALED cycles are never opened writable."""
    state = Path(state).absolute()
    def safe(path):
        path = Path(path).absolute()
        if not path.is_relative_to(state):
            raise RuntimeError('Recovery path escaped research state')
        for part in [path, *path.parents]:
            if part.is_symlink() or part.is_junction():
                raise RuntimeError('Linked recovery path')
        if path.is_file() and path.stat().st_nlink != 1:
            raise RuntimeError('Hard-linked recovery file')
        return path
    with safe(state / 'worker.lock').open('a+b') as handle:
        if os.name == 'posix':
            import fcntl
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        else:
            import msvcrt
            handle.seek(0); handle.write(b'0'); handle.flush(); handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        recovered = []
        paths = [state / 'continuous/ledger.sqlite3'] + list((state / 'continuous/cycles').glob('*/research.sqlite3'))
        for path in paths:
            safe(path)
            if path.parent != state / 'continuous' and safe(path.parent / 'SEALED.json').exists():
                continue
            journal = safe(Path(str(path) + '-journal'))
            if not path.exists() or not journal.exists() or journal.stat().st_size <= 512:
                continue
            db = sqlite3.connect(path, timeout=1)
            try:
                db.execute('SELECT COUNT(*) FROM sqlite_master').fetchone()
            finally:
                db.close()
            recovered.append(path.relative_to(state).as_posix())
        return recovered


def lock_memory(resource_module=None, libc=None, status_path=Path('/proc/self/status')):
    if resource_module is None:
        import resource as resource_module
    address = resource_module.getrlimit(resource_module.RLIMIT_AS)
    locked = resource_module.getrlimit(resource_module.RLIMIT_MEMLOCK)
    if not all(0 < n <= CAP for n in address) or not all(n >= CAP for n in locked):
        raise RuntimeError('Required address-space/memlock limits are not enforced')
    if libc is None:
        libc = ctypes.CDLL(None, use_errno=True)
    libc.mlockall.argtypes = [ctypes.c_int]
    libc.mlockall.restype = ctypes.c_int
    if libc.mlockall(1 | 2) != 0:
        raise RuntimeError('mlockall failed; research must remain paused')
    status = dict(line.split(':', 1) for line in status_path.read_text().splitlines() if ':' in line)
    if int(status['VmLck'].split()[0]) <= 0 or int(status['VmSwap'].split()[0]) != 0:
        raise RuntimeError('Locked memory/no-swap verification failed')
    return {'address_space_limit_bytes': list(address), 'memory_lock_limit_bytes': list(locked),
            'locked_kib': int(status['VmLck'].split()[0]), 'swap_kib': 0,
            'research_memory_lock': 'CURRENT_AND_FUTURE'}


def main():
    if sys.argv[1:] not in ([], ['--probe'], ['--ready']):
        raise RuntimeError('Only the pinned bootstrap or memory-only probe is allowed')
    result = lock_memory()
    print(json.dumps(result), flush=True)
    if sys.argv[1:] == ['--probe']:
        return
    try:
        recovered = recover_interrupted_sqlite()
    except BlockingIOError:
        # A skipped condition may trigger OnSuccess on the installed systemd.
        raise SystemExit(255)
    if recovered:
        print(json.dumps({'sqlite_recovered': recovered}), flush=True)
    command = 'ready' if sys.argv[1:] == ['--ready'] else 'run'
    sys.argv = [str(BOOTSTRAP), command]
    runpy.run_path(str(BOOTSTRAP), run_name='__main__')


if __name__ == '__main__':
    main()
