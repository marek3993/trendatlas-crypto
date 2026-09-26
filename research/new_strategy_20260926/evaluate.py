import math
import numpy as np
import pandas as pd
import ledger,signals
from common import candidate_id

def concentration(run):
    eps=run['episodes'];total=sum(e['log_growth'] for e in eps)
    assets={a:sum(e['log_growth'] for e in eps if e['asset']==a) for a in sorted({e['asset'] for e in eps})}
    if total<=0:return dict(asset_concentration=None,trade_concentration=None,attribution_valid=False,asset_log_growth=assets)
    return dict(asset_concentration=max([max(0.,v)/total for v in assets.values()],default=0.),trade_concentration=max([max(0.,e['log_growth'])/total for e in eps],default=0.),attribution_valid=True,asset_log_growth=assets)

def replay(m,t,year,*,mult=1.,lag=2,details=False,capital_scale=1.):
    return ledger.simulate(m,t,start=f'{year}-01-01',end=f'{year}-12-31 20:00:00',mult=mult,lag=lag,details=details,capital_scale=capital_scale)

def evaluate(m,cfg,year,*,scope='development',ablation=None,keep=False,capital_scale=1.,double_scale=1.,delay_scale=1.):
    t=signals.target(m,cfg,ablation)
    row=dict(candidate_id=candidate_id(cfg),candidate=cfg,scope=scope,year=year,status='VALID',ablation=ablation)
    stage='nominal'
    try:
        nominal=replay(m,t,year,details=keep,capital_scale=capital_scale);r=ledger.summarize(nominal);r.update(concentration(nominal));row.update(r)
        stage='double_cost';doubled=replay(m,t,year,mult=2.,capital_scale=double_scale)
        stage='delayed_fill';late=replay(m,t,year,lag=3,capital_scale=delay_scale)
        double=ledger.summarize(doubled);delayed=ledger.summarize(late)
        row.update(double_cost_cagr=double['cagr'],double_cost_mdd=double['mdd'],delayed_cagr=delayed['cagr'],delayed_mdd=delayed['mdd'])
        if keep:return row,dict(nominal=nominal,double=doubled,delayed=late,signals=t)
    except ValueError as exc:
        row=dict(candidate_id=candidate_id(cfg),candidate=cfg,scope=scope,year=year,status='REJECT_DATA_OR_EXECUTION',reason=str(exc),execution_stage=stage,ablation=ablation)
    return (row,None) if keep else row

def feasible(r,dd=.35):
    return r['status']=='VALID' and r['cagr']>0 and r['mdd']<=dd and r['double_cost_cagr']>0 and r['delayed_cagr']>0

OBJECTIVES=[('cagr',1),('mdd',-1),('sharpe',1),('calmar',1),('turnover',-1),('costs',-1),('double_cost_cagr',1),('delayed_cagr',1),('without_three_trades',1),('asset_concentration',-1),('trade_concentration',-1)]
def vec(r):
    if r['status']!='VALID':return [-math.inf]*len(OBJECTIVES)
    return [float(r[k])*direction if r.get(k) is not None else -math.inf for k,direction in OBJECTIVES]
def dominates(a,b):
    av,bv=vec(a),vec(b);return all(x>=y for x,y in zip(av,bv)) and any(x>y for x,y in zip(av,bv))
def fronts(rows):
    left=list(rows);out=[]
    while left:
        front=[r for r in left if not any(dominates(s,r) for s in left if s is not r)]
        out.append(front);ids={r['candidate_id'] for r in front};left=[r for r in left if r['candidate_id'] not in ids]
    return out
def crowd(front):
    n=len(front);score={r['candidate_id']:0. for r in front}
    for k,direction in OBJECTIVES:
        ordered=sorted(front,key=lambda r:(vec(r)[[x[0] for x in OBJECTIVES].index(k)],r['candidate_id']))
        finite=[r for r in ordered if r['status']=='VALID' and r.get(k) is not None]
        if len(finite)<2:continue
        lo,hi=float(finite[0][k]),float(finite[-1][k]);span=abs(hi-lo)
        if span==0:continue
        score[finite[0]['candidate_id']]=math.inf;score[finite[-1]['candidate_id']]=math.inf
        for i in range(1,len(finite)-1):score[finite[i]['candidate_id']]+=abs(finite[i+1][k]-finite[i-1][k])/span
    return sorted(front,key=lambda r:(-score[r['candidate_id']],r['candidate_id']))
def survivors(rows,n=6):
    result=[]
    for qualified in [True,False]:
        subset=[r for r in rows if feasible(r)==qualified]
        for front in fronts(subset):result+=crowd(front)
    return result[:n]
def champion(rows):
    pool=[r for r in rows if feasible(r)] or [r for r in rows if r['status']=='VALID']
    if not pool:return min(rows,key=lambda r:r['candidate_id'])
    return sorted(fronts(pool)[0],key=lambda r:(r['mdd'],-r['calmar'],-r['sharpe'],-r['cagr'],r['turnover'],r['candidate_id']))[0]

def stitch(runs):
    daily=[];eps=[];fills=[];nav=1.
    for year,r in sorted(runs.items()):
        d=r['daily'].copy();d.equity*=nav;nav=d.equity.iloc[-1];daily.append(d)
        for ep in r['episodes']:eps.append(dict(ep,fold=year,id=len(eps)+1))
        fills+=r['fills']
    out=dict(daily=pd.concat(daily),episodes=eps,fills=fills,liquidations=sum(r['liquidations'] for r in runs.values()))
    metrics=ledger.summarize(out);metrics.update(concentration(out));return metrics,out
