"""Completed daily prices only; liquidity selection is not relative-return momentum."""
import itertools
import numpy as np
import pandas as pd
from .common import config,cid,validate,SPEC

def trend(m,rule,confirm=0,h=0.0):
    p=m['close'];hi=m['high'];lo=m['low']
    if rule.startswith('sma'):
        ref=p.rolling(int(rule[3:])).mean();up=p>ref*(1+h);down=p<ref*(1-h)
    elif rule.startswith('dual'):
        fast,slow=map(int,rule[4:].split('_'));f=p.rolling(fast).mean();s=p.rolling(slow).mean()
        up=(p>s*(1+h))&(f>s*(1+h));down=(p<s*(1-h))&(f<s*(1-h))
    elif rule.startswith('breakout'):
        n=int(rule[8:]);up=p>hi.rolling(n).max().shift(1)*(1+h);down=p<lo.rolling(n).min().shift(1)*(1-h)
    elif rule.startswith('mom'):
        r=p/p.shift(int(rule[3:]))-1;up=r>h;down=r<(-h)
    elif rule.startswith('combo'):
        a=trend(m,'sma200' if rule=='combo_sma_mom' else 'breakout55',0,h);b=trend(m,'mom180',0,h)
        up=pd.DataFrame((a==1)&(b==1),index=p.index,columns=p.columns);down=pd.DataFrame((a==-1)&(b==-1),index=p.index,columns=p.columns)
    else:raise ValueError(rule)
    up=up.to_numpy();down=down.to_numpy();state=np.zeros(p.shape[1],int);uc=state.copy();dc=state.copy();out=np.zeros(p.shape,int)
    for i in range(len(p)):
        uc=np.where(up[i],uc+1,0);dc=np.where(down[i],dc+1,0)
        state=np.where(uc>=max(1,confirm),1,np.where(dc>=max(1,confirm),-1,state))
        state=np.where(np.isfinite(p.iloc[i].to_numpy()),state,0)
        if rule.startswith('combo'):state=np.where(up[i]|down[i],state,0)
        out[i]=state
    return out

def risk_weights(m,i,ids,kind,k):
    if not ids:return np.array([])
    if kind=='equal':w=np.ones(len(ids))
    else:
        v=m['vol'].iloc[i,ids].to_numpy();w=1/np.maximum(np.where(np.isfinite(v),v,1),.1)
        if kind=='equal_risk' and len(ids)>1:
            r=m['daily_returns'].iloc[max(0,i-59):i+1,ids]
            cov=r.cov(min_periods=30).to_numpy();diag=np.maximum((np.maximum(np.where(np.isfinite(v),v,1),.1)**2)/365.25,1e-6)
            cov=np.where(np.isfinite(cov),cov,0);cov=.5*cov+.5*np.diag(diag)
            for _ in range(60):
                w=w/w.sum();rc=w*(cov@w);target=max(float(w@cov@w)/len(w),1e-12)
                w*=np.sqrt(target/np.maximum(rc,1e-12))
    return w/w.sum()*len(ids)/k

def targets(m,c,benchmark=False):
    c=validate(c);days=m['days'];n=len(m['assets']);btc=m['assets'].index('BTCUSDT');out=np.zeros((len(days),n));events=np.zeros(len(days),bool)
    s=trend(m,'sma200' if benchmark else c['signal'],0 if benchmark else c['confirm'],0.0 if benchmark else c['hysteresis'])
    if benchmark:s=np.where(m['close'].to_numpy()>m['close'].rolling(200).mean().to_numpy(),1,0)
    ok=m['eligible'].to_numpy();base=m['base'].to_numpy();rank=m['rank'].to_numpy();old=np.zeros(n)
    if '_fund7' not in m:
        fund_daily=np.zeros((len(days),n));first=days[0].value;one_day=pd.Timedelta(days=1).value
        for t,j,r in m['funding']:
            i=(t.value-first)//one_day
            if 0<=i<len(days):fund_daily[i,j]+=r
        m['_fund7']=pd.DataFrame(fund_daily).rolling(7).sum().to_numpy()*365.25/7
    fund7=m['_fund7']
    betas={}
    if c['family']=='D' and c['recipe']=='beta_neutral':
        br=m['daily_returns'].iloc[:,btc];var=br.rolling(180,min_periods=90).var()
        for j in range(n):betas[j]=(m['daily_returns'].iloc[:,j].rolling(180,min_periods=90).cov(br)/var).clip(.25,3).to_numpy()
    for i,d in enumerate(days):
        schedule=benchmark or (d.weekday()==6 if c['cadence']=='weekly' else d.is_month_end)
        w=old.copy();positive=s[i]>0;allowed=(base[i] if (benchmark or (c['family']=='F' and c['scope']!='liquid5') or (c['family']=='D' and c['recipe']=='btc_regime')) else ok[i]).copy()
        if c['family']=='G':allowed[btc]=base[i,btc]
        # Entry/reweight cadence; a confirmed invalidation can exit daily.
        if benchmark:
            w[:]=0
            if positive[btc] and base[i,btc]:w[btc]=1
        elif schedule:
            w[:]=0;ids=sorted(np.flatnonzero(ok[i]),key=lambda j:(rank[i,j],m['assets'][j]))
            f=c['family']
            if f=='F':
                chosen=ids[:5] if c['scope']=='liquid5' else [m['assets'].index(c['scope']+'USDT')]
                for j in chosen:
                    if positive[j] and allowed[j]:w[j]=1/(5 if c['scope']=='liquid5' else 1)
            elif f=='G':
                if positive[btc] and base[i,btc]:
                    w[btc]=1-c['satellite'];alts=[j for j in ids if j!=btc][:c['satellite_k']]
                    for j in alts:
                        if positive[j]:w[j]=c['satellite']/c['satellite_k']
            elif f=='H':
                chosen=ids[:c['top_k']];rw=risk_weights(m,i,chosen,c['weighting'],c['top_k'])
                for j,v in zip(chosen,rw):w[j]=v if positive[j] else 0
            elif f=='D':
                if c['recipe']=='btc_regime':
                    if base[i,btc]:w[btc]=s[i,btc]*c['gross']
                else:
                    chosen=ids[:c['top_k']];rw=risk_weights(m,i,chosen,c['weighting'],c['top_k'])
                    for j,v in zip(chosen,rw):w[j]=v*s[i,j]*c['gross']
                    if c['recipe']=='funding_aware':w=np.where(np.sign(w)*fund7[i]>.20,0,w)
                    if c['recipe']=='beta_neutral':
                        b=np.array([betas[j][i] for j in range(n)]);b=np.where(np.isfinite(b),b,1.)
                        lb=float((w.clip(0)*b).sum());sb=float((-w.clip(max=0)*b).sum())
                        if not lb or not sb:w[:]=0
                        else:
                            w=np.where(w>0,w*sb/(lb+sb),w*lb/(lb+sb));gross=np.abs(w).sum()
                            if gross:w*=c['gross']/gross
        if c['family']=='D' and not benchmark:
            w=np.where(allowed&(s[i]*w>0),w,0)
        else:w=np.where(allowed&positive,w,0)
        if c['family']=='G' and not (positive[btc] and base[i,btc]):w[:]=0
        events[i]=schedule or np.any(np.abs(w-old)>1e-12);out[i]=w;old=w
    return out,events
