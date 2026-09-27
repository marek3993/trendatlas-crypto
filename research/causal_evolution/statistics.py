"""Diagnostic statistics; dependence, selection and small samples stay explicit.

References: Bailey/Lopez de Prado DSR (2014), Bailey et al PBO (2017),
White Reality Check (2000). Centered paired bootstrap+Holm is NOT Hansen SPA.
"""
import itertools
import math
from statistics import NormalDist
import numpy as np
from .protocol import CONTRACT

def metrics(log_returns):
    x = np.asarray(log_returns, float)
    r = np.expm1(x); sd = r.std(ddof=1) if len(r)>1 else 0.
    cagr = float(np.expm1(np.clip(x.mean()*365.25,-700,700))) if len(x) else 0.
    return dict(cagr=cagr, sharpe=float(r.mean()/sd*np.sqrt(365.25)) if sd>1e-12 else 0.)

def holm(pvalues):
    p = np.asarray(pvalues,float); order=np.argsort(p); out=np.ones(len(p)); running=0.
    for j,i in enumerate(order):
        running=max(running,min(1.,(len(p)-j)*p[i]));out[i]=running
    return out.tolist()

def dsr(log_returns, trials, trial_sharpes):
    x=np.expm1(np.asarray(log_returns,float)); n=len(x)
    if n<3 or x.std(ddof=1)<1e-12:
        return dict(probability=0.,status='INCONCLUSIVE',trials=trials,effective_days=0)
    sr=float(x.mean()/x.std(ddof=1)); z=(x-x.mean())/x.std(ddof=0)
    skew=float(np.mean(z**3));kurt=float(np.mean(z**4));N=max(2,int(trials))
    normal=NormalDist();gamma=.5772156649015329
    srs=np.asarray(trial_sharpes,float)/np.sqrt(365.25)
    spread=max(float(np.std(srs,ddof=1)) if len(srs)>1 else 0.,1/math.sqrt(n))
    expected=spread*((1-gamma)*normal.inv_cdf(1-1/N)+gamma*normal.inv_cdf(1-1/(N*math.e)))
    # Positive serial correlation reduces effective observations; never enlarges n.
    ac=[]
    for lag in range(1,min(31,n//4)):
        a=x[:-lag];b=x[lag:]
        corr=float(np.corrcoef(a,b)[0,1]) if a.std()>1e-12 and b.std()>1e-12 else 0.
        ac.append(max(0.,corr)*(1-lag/n))
    eff=n/(1+2*sum(ac));den=max(1e-12,1-skew*sr+(kurt-1)*sr*sr/4)
    prob=normal.cdf((sr-expected)*math.sqrt(max(1,eff-1))/math.sqrt(den))
    return dict(probability=prob,trials=int(trials),effective_days=eff,
                expected_max_daily_sharpe=expected,observed_daily_sharpe=sr,
                skew=skew,kurtosis=kurt,status='DIAGNOSTIC_NOT_GLOBAL_INDEPENDENCE')

def paired_bootstrap(candidate, benchmark, episodes, replicates=None):
    c=np.asarray(candidate,float); b=np.asarray(benchmark,float)
    if c.shape!=b.shape or not len(c):raise ValueError('Matched daily returns required')
    cfg=CONTRACT['statistics']; reps=replicates or cfg['bootstrap_replicates']; block=cfg['mean_block_days']
    rng=np.random.default_rng(cfg['bootstrap_seed']); rows=[]; centered=c-b-np.mean(c-b)
    pcount=0; observed=float(np.mean(c-b)); n=len(c)
    for _ in range(reps):
        indices=np.empty(n,int);indices[0]=rng.integers(n)
        for j in range(1,n):indices[j]=rng.integers(n) if rng.random()<1/block else (indices[j-1]+1)%n
        x=c[indices]; y=b[indices]; m=metrics(x)
        rows.append([m['cagr'],m['sharpe'],float(np.mean(x-y)*365.25)])
        pcount+=float(centered[indices].mean())>=observed
    lo,hi=np.quantile(rows,[.025,.975],axis=0)
    enough=n>=cfg['minimum_days'] and episodes>=cfg['minimum_closed_episodes'] and n/block>=cfg['minimum_effective_blocks']
    return dict(status='DIAGNOSTIC' if enough else 'INCONCLUSIVE',days=n,closed_episodes=episodes,
                effective_blocks=n/block,replicates=reps,
                cagr_ci=[float(lo[0]),float(hi[0])],sharpe_ci=[float(lo[1]),float(hi[1])],
                excess_log_growth_ci=[float(lo[2]),float(hi[2])],pvalue=(pcount+1)/(reps+1))

def cscv(matrix):
    """Retrospective contiguous-block diagnostic ONLY; never a shuffled fitting split."""
    x=np.asarray(matrix,float); cfg=CONTRACT['statistics']
    if x.ndim!=2 or x.shape[1]<cfg['cscv_min_candidates'] or x.shape[0]<cfg['minimum_days']:
        return dict(status='INCONCLUSIVE',pbo=None,days=int(x.shape[0]) if x.ndim else 0,
                    candidates=int(x.shape[1]) if x.ndim==2 else 0)
    if np.unique(x.round(12),axis=1).shape[1]<cfg['cscv_min_candidates']:
        return dict(status='INCONCLUSIVE',pbo=None,reason='insufficient_distinct_return_paths')
    blocks=np.array_split(np.arange(len(x)),cfg['cscv_blocks']); logits=[]
    for choose in itertools.combinations(range(len(blocks)),len(blocks)//2):
        train=np.concatenate([blocks[i] for i in choose]);test=np.concatenate([blocks[i] for i in range(len(blocks)) if i not in choose])
        def score(ids):
            r=np.expm1(x[ids]);return r.mean(axis=0)/np.maximum(r.std(axis=0,ddof=1),1e-12)
        ins=score(train);outs=score(test); best=np.flatnonzero(ins==ins.max())
        # Average tied winners/ranks: no lexical advantage for duplicate CASH books.
        percent=[]
        for i in best:
            rank=1+np.sum(outs<outs[i])+.5*(np.sum(outs==outs[i])-1)
            percent.append(rank/(len(outs)+1))
        p=float(np.mean(percent));logits.append(math.log(p/(1-p)))
    return dict(status='DIAGNOSTIC',pbo=float(np.mean(np.array(logits)<=0)),
                splits=len(logits),days=len(x),candidates=x.shape[1],logits=logits,
                warning='CSCV diagnostic reorders blocks for diagnosis, never evolution; not fresh prospective evidence')

def pareto_front(rows):
    """Each vector already has maximization orientation. No scalar weighted fitness."""
    if not rows:return []
    a=np.array([r['vector'] for r in rows],float)
    return [i for i in range(len(rows)) if not any(np.all(a[j]>=a[i]) and np.any(a[j]>a[i]) for j in range(len(rows)) if i!=j)]

def survivors(rows, count=6):
    remaining=list(rows); selected=[]
    while remaining and len(selected)<count:
        ids=pareto_front(remaining);front=[remaining[i] for i in ids]
        if len(selected)+len(front)<=count: chosen=front
        else:
            a=np.array([r['vector'] for r in front]); distance=np.zeros(len(front))
            for col in a.T:
                order=np.argsort(col,kind='stable');span=col[order[-1]]-col[order[0]]
                if span<1e-12:continue
                distance[order[0]]=distance[order[-1]]=np.inf
                for j in range(1,len(order)-1):distance[order[j]]+=(col[order[j+1]]-col[order[j-1]])/span
            order=sorted(range(len(front)),key=lambda i:(-distance[i],front[i]['complexity'],front[i]['id']))
            chosen=[front[i] for i in order[:count-len(selected)]]
        selected.extend(chosen); remaining=[r for i,r in enumerate(remaining) if i not in ids]
    return selected
