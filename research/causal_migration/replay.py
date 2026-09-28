"""Fixed existing-candidate replay without opening/writing the experiment DB."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import time
for k in ('OPENBLAS_NUM_THREADS','OMP_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS'):os.environ[k]='1'
sys.path.insert(0,str(Path(__file__).resolve().parent))
import runtime as r


def choose(state):
    r.legacy.load_engine(r.ENGINE)
    from research.causal_evolution.vendor.common import cid
    db=r.legacy.readonly(Path(state)/'candidates.sqlite')
    seeded={x[0] for x in db.execute("SELECT candidate FROM trials WHERE run='2024:F_spot:1701:deterministic' AND source='seed'")}
    for key,request,metrics in db.execute('SELECT cache_key,request,metrics FROM evaluations ORDER BY cache_key'):
        q,m=json.loads(request),json.loads(metrics)
        if cid(q['genes']) in seeded and q['period']['scope']=='inner_validation' and m['trades']>0 and not q['benchmark'] and not q['cash']:
            db.close()
            return dict(candidate_id=cid(q['genes']),search_seed=1701,source_run='2024:F_spot:1701:deterministic',source_evaluation=key,
                        request=dict(q,stress='double_cost'),rtol=1e-10,atol=1e-10,
                        tolerance_source='frozen evaluator.prefix_audit numeric replay tolerance',signal_comparison='exact')
    raise RuntimeError('No existing traded seed candidate for replay')


def replay(spec):
    import platform,sqlite3
    import numpy as np
    import pandas as pd
    r.legacy.load_engine(r.ENGINE)
    from research.causal_evolution.evaluator import Evaluator,clean,audit_book
    from research.causal_evolution.vendor.signals import targets
    from research.causal_evolution.vendor.ledger import replay as ledger
    from research.causal_evolution.protocol import CONTRACT
    class Context:
        def meta(self,key,default=None):return r.POLICY['fingerprint'] if key=='fingerprint' else default
    start=time.monotonic();q=spec['request'];e=Evaluator(Context());market=e.model(q['track'],q['period']['end'])
    sig=targets(market,q['genes'])
    book=ledger(market,sig,q['period']['start'],q['period']['end'],capital=q['capital'],
                gross_limit=q['genes']['gross'] if q['track']=='perp' else 1.,
                max_holding_days=CONTRACT['split']['max_position_days'],details=True,cost_mult=2.)
    audit=audit_book(book,market)
    if not audit['pass_audit'] or not book['fills']:raise RuntimeError('Replay audit/fills failed')
    daily=book['daily'].reset_index();daily['date']=daily['date'].astype(str)
    nav=np.r_[q['capital'],book['daily'].nav.to_numpy()]
    # NaNs become null, preserving the nonfinite mask for comparison.
    payload=clean(dict(signals=sig[0].tolist(),signal_events=sig[1].tolist(),fills=book['fills'],orders=book['orders'],
                       daily=daily.to_dict('records'),daily_returns=(nav[1:]/nav[:-1]-1).tolist(),metrics=book['metrics'],audit=audit))
    return dict(spec=spec,payload=payload,environment=dict(python=platform.python_version(),architecture=platform.machine(),numpy=np.__version__,pandas=pd.__version__,sqlite=sqlite3.sqlite_version),elapsed_seconds=time.monotonic()-start)


def compare(left,right):
    import math
    if left['spec']!=right['spec']:raise RuntimeError('Replay specs differ')
    spec=left['spec'];differences=[];largest=0.;exact=True
    def walk(a,b,path=''):
        nonlocal largest,exact
        if isinstance(a,dict):
            if not isinstance(b,dict) or set(a)!=set(b):raise RuntimeError('Replay structure mismatch '+path)
            for k in a:walk(a[k],b[k],path+'/'+str(k))
        elif isinstance(a,list):
            if not isinstance(b,list) or len(a)!=len(b):raise RuntimeError('Replay length mismatch '+path)
            for i,(x,y) in enumerate(zip(a,b)):walk(x,y,path+'/'+str(i))
        elif isinstance(a,float) and isinstance(b,(float,int)) and not isinstance(b,bool):
            delta=abs(a-b);largest=max(largest,delta);exact=exact and a==b
            allowed=0 if path.startswith(('/signals/','/signal_events/')) else spec['atol']+spec['rtol']*abs(b)
            if delta>allowed:differences.append(path)
        elif a!=b:exact=False;differences.append(path)
    walk(left['payload'],right['payload'])
    result=dict(pass_replay=not differences,exact_numeric_equality=exact,maximum_absolute_delta=largest,mismatches=differences[:20],
                candidate_id=spec['candidate_id'],seed=spec['search_seed'],stress='double_cost',period=spec['request']['period'],
                fills=len(left['payload']['fills']),rtol=spec['rtol'],atol=spec['atol'],environments=[left['environment'],right['environment']])
    if differences:raise RuntimeError(json.dumps(result))
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('command',choices=['choose','run','compare']);p.add_argument('--state',type=Path,default=r.STATE);p.add_argument('--spec',type=Path);p.add_argument('--left',type=Path);p.add_argument('--right',type=Path);p.add_argument('--output',type=Path,required=True);p.add_argument('--pi',action='store_true');a=p.parse_args()
    if a.pi:
        r.legacy.load_engine(r.ENGINE)
        from research.causal_evolution.resources import lock_memory
        lock_memory()
    result=choose(a.state) if a.command=='choose' else replay(json.loads(a.spec.read_text())) if a.command=='run' else compare(json.loads(a.left.read_text()),json.loads(a.right.read_text()))
    r.atomic(a.output,result)
    print(json.dumps(result if a.command!='run' else dict(output=str(a.output),elapsed_seconds=result['elapsed_seconds'],environment=result['environment']),sort_keys=True))
