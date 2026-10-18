"""Sole Clean orchestrator: public signal -> TS multi-account worker -> public publication."""
from __future__ import annotations
import argparse
import fcntl
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--no-submit',action='store_true');args=p.parse_args()
    state=Path(os.environ.get('TRENDATLAS_CLEAN_STATE_DIR','/var/lib/trendatlas-clean/state'))
    state.mkdir(parents=True,exist_ok=True)
    with (state/'production.lock').open('a') as lock:
        fcntl.flock(lock.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        subprocess.run([sys.executable,str(ROOT/'scripts/production/run_clean_5050.py'),'--data-dir',str(state.parent/'data'),'--state-dir',str(state),'--universe','all','--refresh'],check=True)
        env=dict(os.environ,TRENDATLAS_CLEAN_WORKER='1',TRENDATLAS_CLEAN_STATE_DIR=str(state),TRENDATLAS_CLEAN_CONFIG='/etc/trendatlas-clean/policy.json')
        node=env.get('TRENDATLAS_NODE','/usr/bin/node')
        base=[node,'--conditions=react-server','--import','tsx']
        result=subprocess.run(base+['scripts/run-clean-multi-account.ts']+(['--no-submit'] if args.no_submit else ['--execute-live']),cwd=ROOT/'web',env=env)
        if not args.no_submit:
            # Publication is independent of individual account failures, and contains no account data.
            subprocess.run(base+['scripts/publish-clean-public.ts'],cwd=ROOT/'web',env=env,check=True)
        return result.returncode

if __name__=='__main__':
    try:raise SystemExit(main())
    except Exception:
        print('Clean cycle stopped; inspect its local status and receipt.',file=sys.stderr);raise SystemExit(2)
