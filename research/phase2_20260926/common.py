from pathlib import Path
import hashlib
import json
import sys
import numpy as np
import pandas as pd
HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
OLD=HERE.parent/'causal_search_20260926'
sys.path.insert(0,str(OLD))
import engine as e
from run import cash_run, write_run

def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def read(path): return json.loads(Path(path).read_text(encoding='utf-8'))
def write(path,value):
    Path(path).parent.mkdir(parents=True,exist_ok=True)
    Path(path).write_text(json.dumps(value,sort_keys=True,indent=2,allow_nan=False)+'\n',encoding='utf-8')
def source_contracts():
    phase=read(ROOT/'source_of_truth/research_phase2_contract.json')
    objectives=read(ROOT/phase['objectives_contract'])
    assert objectives['targets']['oos_cagr_range']==[1.5,2.0]
    assert not objectives['orders_allowed'] and not objectives['production_promotion_allowed']
    return phase,objectives
def enhanced_market(m=None):
    m=m or e.load_market();c=pd.DataFrame(m.prices[:,:,3],index=m.dates)
    for n in [20,30,55,60,90,100,180,200,365]:
        m.features['mom'+str(n)]=(c/c.shift(n)-1).to_numpy()
        m.features['sma'+str(n)]=c.rolling(n,min_periods=n).mean().to_numpy()
        m.features['high'+str(n)]=c.shift(1).rolling(n,min_periods=n).max().to_numpy()
        m.features['low'+str(n)]=c.shift(1).rolling(n,min_periods=n).min().to_numpy()
    for n,out in [(55,20),(100,55)]:
        active=np.zeros_like(c,dtype=bool)
        for i in range(1,len(c)):
            active[i]=(active[i-1] | (m.features['close'][i]>m.features['high'+str(n)][i])) & (m.features['close'][i]>=m.features['low'+str(out)][i])
        m.features['breakout'+str(n)]=active
    return m
def metrics(run):
    x=e.summarize(run)
    folds=[]
    for year in run['dates'].year.unique():
        r=run['rows'][run['dates'].year==year,0];folds.append(float(np.prod(1+r)-1))
    x.update(fold_returns=folds,profitable_fold_fraction=sum(v>0 for v in folds)/len(folds),worst_fold_return=min(folds))
    return x
def no_risk(): return dict(catastrophic=0,trail=0,tp=0,tp_atr=2,cooldown=3)
def legacy_spec(): return read(OLD/'pre_registration.json')
def fingerprints(paths): return {p.relative_to(ROOT).as_posix():sha(p) for p in paths}
