"""Pinned OS-only memory restriction; original engine release is never modified."""
import ctypes
import json
from pathlib import Path
import runpy
import sys

CAP = 384 * 1024 * 1024
BOOTSTRAP = Path('/opt/trendatlas-research/releases/d534035a216a134cce610f80eec32afb8f0461bd/research_os/dev_only/evolution_worker/bootstrap.py')


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
            'research_memory_lock': 'CURRENT_AND_FUTURE', 'engine_release_unchanged': True}


def main():
    if sys.argv[1:] not in ([], ['--probe']):
        raise RuntimeError('Only the pinned bootstrap or memory-only probe is allowed')
    result = lock_memory()
    print(json.dumps(result), flush=True)
    if sys.argv[1:] == ['--probe']:
        return
    sys.argv = [str(BOOTSTRAP), 'run']
    runpy.run_path(str(BOOTSTRAP), run_name='__main__')


if __name__ == '__main__':
    main()
