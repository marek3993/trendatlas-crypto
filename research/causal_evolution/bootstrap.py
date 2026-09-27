"""Pi-only, pinned research entry point. Must run before numpy/BLAS imports."""
import ctypes
import json
import os
from pathlib import Path
import sys

RELEASE=Path(__file__).resolve().parents[2]
BASE=Path('/var/lib/trendatlas-research/causal-v1')

def main():
    if sys.argv[1:] not in (['ready'],['run'],['probe'],['broker'],['maintain']):raise RuntimeError('Unsupported entry point')
    for key in ('OPENBLAS_NUM_THREADS','OMP_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS'):os.environ[key]='1'
    sys.path.insert(0,str(RELEASE))
    from research.causal_evolution.protocol import CONTRACT,atomic
    command=sys.argv[1]
    if command=='ready':
        status=BASE/'current'/'status.json'
        if status.exists() and json.loads(status.read_text()).get('status') in ('SEALED','FAILED','WAITING_FOR_NEW_DATA'):
            # 255 prevents OnSuccess from admitting a stopped/sealed cycle.
            return 255
        thermal=list(Path('/sys/class/thermal').glob('thermal_zone*/temp'))
        if not thermal or max(int(p.read_text())/1000 for p in thermal)>=CONTRACT['runtime']['thermal_resume_c']:return 255
        import shutil
        if shutil.disk_usage(BASE).free<CONTRACT['runtime']['disk_free_reserve_mib']*1024**2:return 255
        return 0
    if command in ('probe','run','broker'):
        import resource
        cap=CONTRACT['runtime']['ram_max_mib']*1024**2
        if any(v<=0 or v>cap for v in resource.getrlimit(resource.RLIMIT_AS)):raise RuntimeError('Missing address-space limit')
        if any(v<cap for v in resource.getrlimit(resource.RLIMIT_MEMLOCK)):raise RuntimeError('Missing memory-lock limit')
        if ctypes.CDLL(None,use_errno=True).mlockall(1|2)!=0:raise RuntimeError('Research memory locking failed')
        if command=='probe':
            import numpy,pandas
            # Load the actual historical PIT census under the same hard memory guard.
            from research.causal_evolution.vendor.data import load
            m=load('spot','2023-09-29')
            status={x.split(':')[0]:x.split(':')[1].strip() for x in Path('/proc/self/status').read_text().splitlines() if ':' in x}
            print(json.dumps(dict(assets=len(m['assets']),numpy=numpy.__version__,pandas=pandas.__version__,memory=status,guard='RLIMIT_AS+mlockall')))
            return 0
    if command=='maintain':
        from research.causal_evolution.resources import lock_memory
        lock_memory()
        from research.causal_evolution.continuation import maintain
        maintain(BASE);return 0
    from research.causal_evolution.cli import main as cli
    state='/var/lib/trendatlas-causal-broker' if command=='broker' else str((BASE/'current').resolve())
    args=['broker' if command=='broker' else 'run','--state',state]
    if command=='run':args+=['--pi']
    return cli(args)

if __name__=='__main__':raise SystemExit(main())
