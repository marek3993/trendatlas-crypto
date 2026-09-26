"""Pure causal decisions: named spot asset or CASH, never a return series."""
import numpy as np
import pandas as pd
from common import validate

def latch(good,confirm):
    state=False;up=down=0;out=[]
    for x in good:
        up=up+1 if x else 0;down=0 if x else down+1
        if up>=confirm:state=True
        if down>=confirm:state=False
        out.append(state)
    return np.array(out,bool)

def target(m,cfg,ablation=None):
    validate(cfg);family=cfg['family'];dc=m['close'];ok=m['daily_eligible'];btc=m['assets'].index('BTCUSDT')
    days=dc.index;held='CASH';selected=[]
    if family=='A':
        slow=dc.rolling(cfg['slow']).mean();fast=dc.BTCUSDT.rolling(cfg['fast']).mean()
        den=ok.sum(axis=1);breadth=((dc>slow)&ok).sum(axis=1)/den.where(den>0)
        threshold=0. if ablation=='no_breadth' else cfg['breadth']
        good=(dc.BTCUSDT>slow.BTCUSDT)&(fast>slow.BTCUSDT)&(breadth>=threshold)
        regime=latch(good.to_numpy(),1 if ablation=='no_confirmation' else cfg['confirm'])
        for i,d in enumerate(days):
            if not ok.iloc[i,btc]:held='CASH'
            due=d.dayofweek==6 if cfg['cadence']=='weekly' else d.is_month_end
            if due:held='BTCUSDT' if regime[i] and ok.iloc[i,btc] else 'CASH'
            selected.append(held)
    elif family=='B':
        n=int(ablation.split('_')[-1]) if ablation and ablation.startswith('lookback_') else cfg['lookback']
        mom=dc/dc.shift(n)-1
        if cfg['blend'] and not (ablation and ablation.startswith('lookback_')):
            mom=sum(dc/dc.shift(k)-1 for k in [30,90,180,365])/4
        vol=dc.pct_change(fill_method=None).rolling(60).std()*np.sqrt(365.25)
        score=mom/vol.clip(lower=.1) if cfg['vol_adjusted'] and ablation!='no_vol_ranking' else mom
        good=ok&mom.gt(0)&np.isfinite(score)
        values=score.to_numpy();valid=good.to_numpy()
        for i,d in enumerate(days):
            if held!='CASH' and not valid[i,m['assets'].index(held)]:held='CASH'
            due=d.dayofweek==6 if cfg['cadence']=='weekly' else d.is_month_end
            if due:
                a=int(np.argmax(np.where(valid[i],values[i],-np.inf)));held=m['assets'][a] if valid[i,a] else 'CASH'
            selected.append(held)
    else:
        slow=dc.BTCUSDT.rolling(cfg['slow']).mean();regime=latch((dc.BTCUSDT>slow).to_numpy(),cfg['confirm'])
        if ablation=='no_daily_regime':regime=np.ones(len(days),bool)
        c=pd.Series(m['prices'][:,btc,3],index=m['dates']);n=cfg['entry_bars']
        entry=c>c.ewm(span=n,adjust=False,min_periods=n).mean() if cfg['entry']=='ema' else c>c.shift(1).rolling(n).max()
        exit_line=c.ewm(span=cfg['exit_bars'],adjust=False,min_periods=cfg['exit_bars']).mean()
        for i,d in enumerate(m['dates']):
            j=m['daily_index'][i];allow=j>=0 and regime[j] and m['eligible'][i,btc]
            if not allow:held='CASH'
            elif ablation=='no_intraday_entry':held='BTCUSDT'
            elif held=='CASH' and bool(entry.iloc[i]):held='BTCUSDT'
            elif held!='CASH' and c.iloc[i]<exit_line.iloc[i]:held='CASH'
            selected.append(held)
        return admitted(m,selected)
    # Expand daily decisions only after that day's last 4h bar has completed.
    expanded=[selected[j] if j>=0 else 'CASH' for j in m['daily_index']]
    return admitted(m,expanded)

def admitted(m,assets):
    out=pd.DataFrame({'asset':assets},index=m['dates']);out['weight']=out.asset.ne('CASH').astype(float)
    for j,a in enumerate(m['assets']):out.loc[out.asset.eq(a)&~m['eligible'][:,j],['asset','weight']]=['CASH',0.]
    return out

def baseline(m,name):
    if name=='CASH':return admitted(m,['CASH']*len(m['dates']))
    if name=='BTC_hold':return admitted(m,['BTCUSDT']*len(m['dates']))
    if name=='BTC_SMA200':
        d=m['close'].BTCUSDT;good=d>d.rolling(200).mean();a=['BTCUSDT' if j>=0 and good.iloc[j] else 'CASH' for j in m['daily_index']]
        return admitted(m,a)
    raise ValueError(name)
