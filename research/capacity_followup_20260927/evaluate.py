import math
import numpy as np
import pandas as pd
import ledger,signals
from common import cid

def benchmark_gate(r,b,outer=False):
    if r.get('status')!='VALID' or b.get('status')!='VALID':return dict(passed=False,reason='Incomplete execution evidence')
    gain=dict(cagr=r['cagr']>=b['cagr']+.05,mdd=r['mdd']<=b['mdd']-.05,sharpe=r['sharpe']>=b['sharpe']+.15,calmar=r['calmar']>=b['calmar']+.25)
    x,y=r.get('positive_profit_asset_share'),b.get('positive_profit_asset_share')
    gain['concentration']=x is not None and y is not None and x<=y-.15
    if outer:gain['folds']=r['profitable_folds']>=b['profitable_folds']+1
    safe=dict(cagr=r['cagr']>=b['cagr']-.10,mdd=r['mdd']<=b['mdd']+.05,sharpe=r['sharpe']>=b['sharpe']-.20,calmar=r['calmar']>=b['calmar']-.30,concentration=x is not None and y is not None and x<=y+.15 if y is not None else True)
    if outer:safe['folds']=r['profitable_folds']>=b['profitable_folds']-1
    return dict(passed=any(gain.values()) and all(safe.values()),improvements=gain,noninferiority=safe)

def replay(m,t,year,capital=100.,mult=1.,lag=2,details=False):
    return ledger.simulate(m,t,start=f'{year}-01-01',end=f'{year}-12-31 20:00:00',capital=capital,mult=mult,lag=lag,details=details)

def evaluate(m,cfg,year,benchmark=None,scope='development',capital=100.,details=False,stress=True):
    row=dict(candidate_id=cid(cfg) if cfg is not None else 'BTC_SMA200',candidate=cfg,year=year,scope=scope,capital=capital,status='VALID')
    t=signals.target(m,cfg) if cfg is not None else signals.benchmark(m);runs={};stage='nominal'
    try:
        runs['nominal']=replay(m,t,year,capital=capital,details=details);row.update(ledger.summarize(runs['nominal']))
        if stress:
            for stage,cost,lag in [('double',2.,2),('delayed',1.,3)]:
                runs[stage]=replay(m,t,year,capital=capital,mult=cost,lag=lag,details=details)
                s=ledger.summarize(runs[stage]);prefix='double_cost' if stage=='double' else 'delayed'
                row[prefix+'_cagr']=s['cagr'];row[prefix+'_mdd']=s['mdd'];row[prefix+'_fill_ratio']=s['entry_fill_ratio']
        if benchmark is not None:row['benchmark_comparison']=benchmark_gate(row,benchmark);row['benchmark_pass']=row['benchmark_comparison']['passed']
    except ledger.UnsafeExecution as exc:
        row.update(status='UNSAFE_EXECUTION',reason=str(exc),failed_stage=stage)
        if exc.partial is not None:runs[stage+'_partial']=exc.partial
    return row,runs,t

OBJECTIVES=[('cagr',1),('mdd',-1),('sharpe',1),('calmar',1),('turnover',-1),('costs',-1),('double_cost_cagr',1),('delayed_cagr',1),('asset_concentration',-1),('trade_concentration',-1)]
def feasible(r):return r['status']=='VALID' and r['cagr']>0 and r['mdd']<=.35 and r.get('double_cost_cagr',-1)>0 and r.get('delayed_cagr',-1)>0 and r.get('benchmark_pass',False)
def vec(r):return [float(r[k])*d if r.get(k) is not None else -math.inf for k,d in OBJECTIVES] if r['status']=='VALID' else [-math.inf]*len(OBJECTIVES)
def dominates(a,b):
    av,bv=vec(a),vec(b);return all(x>=y for x,y in zip(av,bv)) and any(x>y for x,y in zip(av,bv))
def fronts(rows):
    left=list(rows);out=[]
    while left:
        f=[r for r in left if not any(dominates(s,r) for s in left if s is not r)];out.append(f);ids={r['candidate_id'] for r in f};left=[r for r in left if r['candidate_id'] not in ids]
    return out
def crowd(front):
    score={r['candidate_id']:0. for r in front}
    for k,d in OBJECTIVES:
        rows=sorted([r for r in front if r['status']=='VALID' and r.get(k) is not None],key=lambda r:(r[k],r['candidate_id']))
        if len(rows)<2 or rows[-1][k]==rows[0][k]:continue
        score[rows[0]['candidate_id']]=score[rows[-1]['candidate_id']]=math.inf;span=rows[-1][k]-rows[0][k]
        for i in range(1,len(rows)-1):score[rows[i]['candidate_id']]+=(rows[i+1][k]-rows[i-1][k])/span
    return sorted(front,key=lambda r:(-score[r['candidate_id']],r['candidate_id']))
def survivors(rows):
    result=[]
    for flag in [True,False]:
        for front in fronts([r for r in rows if feasible(r)==flag]):result+=crowd(front)
    return result[:6]
def champion(rows):
    pool=[r for r in rows if feasible(r)] or [r for r in rows if r['status']=='VALID']
    if not pool:return min(rows,key=lambda r:r['candidate_id'])
    return min(fronts(pool)[0],key=lambda r:(r['mdd'],-r['calmar'],-r['sharpe'],-r['cagr'],r['turnover'],r['candidate_id']))
def stitch(runs):
    d=[];episodes=[];orders=[];fills=[];nav=1.
    for year,r in sorted(runs.items()):
        part=r['daily'].copy();part.equity*=nav;nav=part.equity.iloc[-1];d.append(part)
        episodes += [dict(ep,fold=year,id=len(episodes)+i+1) for i,ep in enumerate(r['episodes'])]
        orders += [dict(o,fold=year) for o in r['orders']];fills += [dict(f,fold=year) for f in r['fills']]
    last=runs[max(runs)];out=dict(daily=pd.concat(d),episodes=episodes,orders=orders,fills=fills,liquidations=0,capital=runs[min(runs)]['capital'],ending_nav=last['ending_nav'],ending_cash=last['ending_cash'],residual_positions=last['residual_positions'],entry_requested=sum(r['entry_requested'] for r in runs.values()),entry_filled=sum(r['entry_filled'] for r in runs.values()),partial_fills=sum(r['partial_fills'] for r in runs.values()))
    return dict(status='VALID',**ledger.summarize(out)),out
