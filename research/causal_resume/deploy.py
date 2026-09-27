"""Research-only systemd drop-ins. Never install over the frozen engine."""
import argparse
from pathlib import Path

import runtime


def dropins(directory, seconds=None):
    policy = runtime.POLICY
    seconds = policy['cooperative_seconds'] if seconds is None else seconds
    if not 0 < seconds <= policy['cooperative_seconds']:
        raise ValueError('Can only shorten activation')
    entry = Path(directory).resolve() / 'runtime.py'
    python = '/opt/trendatlas-research/venvs/causal-v1/bin/python3 -I -B'
    clean = '/usr/bin/env -i PATH=/usr/bin:/bin LANG=C.UTF-8 HOME=/nonexistent OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 '
    condition = f'{clean}{python} {entry} ready'
    return {
        'trendatlas-evolution-worker.service': (
            '[Service]\nExecCondition=\nExecCondition='+condition+'\n'
            'ExecCondition=/usr/bin/python3 -I -B '+str(runtime.ENGINE)+'/research/causal_evolution/gate.py\n'
            'ExecStart=\nExecStart='+clean+python+' '+str(entry)+' run --seconds '+str(seconds)+'\n'
            'TimeoutStartSec=60s\nRuntimeMaxSec='+str(policy['hard_timeout_seconds'])+'s\n'
            'TimeoutStopSec='+str(policy['stop_timeout_seconds'])+'s\n'),
        'trendatlas-evolution-dispatch.service': (
            '[Service]\nExecCondition=\nExecCondition='+condition+'\nTimeoutStartSec=60s\n'
            # SQLite mode=ro may need to create WAL/SHM coordination files after
            # the last writer closes. Only the research cycles path is writable.
            'ReadWritePaths=/var/lib/trendatlas-research/causal-v1/cycles\n'),
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--destination', required=True)
    p.add_argument('--seconds', type=int)
    args = p.parse_args()
    # Render only; reviewed files can be installed and systemd-verified separately.
    for unit, text in dropins(Path(__file__).resolve().parent, args.seconds).items():
        path = Path(args.destination)/(unit+'.d')
        path.mkdir(parents=True, exist_ok=True)
        (path/'50-causal-resume.conf').write_text(text)


if __name__ == '__main__':
    main()
