import math
from common import cid
OBJECTIVES=[('cagr',1),('mdd',-1),('sharpe',1),('calmar',1),('turnover',-1)]
def gate(r,b,folds=False):
    gains={'cagr':r['cagr']>=b['cagr']+.05,'mdd':r['mdd']<=b['mdd']-.05,'sharpe':r['sharpe']>=b['sharpe']+.15,'calmar':r['calmar']>=b['calmar']+.25}
    x,y=r.get('asset_concentration'),b.get('asset_concentration');gains['concentration']=x is not None and y is not None and x<=y-.15
    safe=dict(cagr=r['cagr']>=b['cagr']-.1,mdd=r['mdd']<=b['mdd']+.05,sharpe=r['sharpe']>=b['sharpe']-.2,calmar=r['calmar']>=b['calmar']-.3)
    if folds:gains['folds']=r['profitable_folds']>b['profitable_folds']
    return dict(passed=bool(r['reliable'] and b['reliable'] and any(gains.values()) and all(safe.values())),gains=gains,noninferiority=safe)
def vec(r):return [r[k]*d for k,d in OBJECTIVES] if r['reliable'] else [-math.inf]*len(OBJECTIVES)
def dominates(a,b):
    x,y=vec(a),vec(b);return all(u>=v for u,v in zip(x,y)) and any(u>v for u,v in zip(x,y))
def fronts(rows):
    left=list(rows);out=[]
    while left:
        f=[r for r in left if not any(dominates(s,r) for s in left if s is not r)];out.append(f);ids={r['candidate_id'] for r in f};left=[r for r in left if r['candidate_id'] not in ids]
    return out
def crowd(front):
    score={r['candidate_id']:0. for r in front}
    for k,_ in OBJECTIVES:
        rows=sorted([r for r in front if r['reliable']],key=lambda r:(r[k],r['candidate_id']))
        if len(rows)<2 or rows[-1][k]==rows[0][k]:continue
        score[rows[0]['candidate_id']]=score[rows[-1]['candidate_id']]=math.inf;span=rows[-1][k]-rows[0][k]
        for i in range(1,len(rows)-1):score[rows[i]['candidate_id']]+=(rows[i+1][k]-rows[i-1][k])/span
    return sorted(front,key=lambda r:(-score[r['candidate_id']],r['candidate_id']))
def survivors(rows):return [r for f in fronts(rows) for r in crowd(f)][:6]
def qualified(r,dev,b):return bool(r['reliable'] and dev['reliable'] and min(r['cagr'],dev['cagr'])>0 and max(r['mdd'],dev['mdd'])<=.35 and gate(r,b)['passed'])
def slots(rows):
    qualified_rows=[r for r in rows if r.get('qualified')];pool=qualified_rows or [r for r in rows if r['reliable']] or rows
    front=fronts(pool)[0];small=[r for r in front if r['mdd']<=.25]
    return dict(aggressive=max(front,key=lambda r:(r['cagr'],-r['mdd'],r['candidate_id'])),robust=min(small or front,key=lambda r:(r['mdd'],-r['calmar'],r['candidate_id'])),compromise=max(front,key=lambda r:(r['calmar'],-r['mdd'],r['candidate_id'])))
