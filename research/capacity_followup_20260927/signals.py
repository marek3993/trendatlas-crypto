"""Concrete spot portfolio weights; no return stream accepted or emitted."""
import numpy as np
from common import validate

def target(m,cfg):
    cfg=validate(cfg);mom=sum(m['momentum'][n] for n in [30,90,180,365])/4 if cfg['blend'] else m['momentum'][cfg['lookback']]
    vol=m['vol'].clip(lower=.1);score=mom/vol if cfg['vol_adjusted'] else mom
    valid=m['daily_eligible']&np.isfinite(score)&np.isfinite(vol)
    if cfg['absolute']:valid &= mom.gt(0)
    names=m['assets'];weights=np.zeros((len(mom),len(names)));events=np.zeros(len(mom),bool);current=np.zeros(len(names))
    val=valid.to_numpy();scores=score.to_numpy();risk=vol.to_numpy()
    for i,d in enumerate(mom.index):
        invalid=(current>0)&~val[i]
        if invalid.any():current[invalid]=0;events[i]=True
        due=d.dayofweek==6 if cfg['cadence']=='weekly' else d.is_month_end
        if due:
            ids=np.flatnonzero(val[i]);ids=sorted(ids,key=lambda j:(-scores[i,j],names[j]))[:cfg['top_k']]
            current=np.zeros(len(names))
            if ids:
                raw=1/risk[i,ids] if cfg['top_k']>1 else np.ones(len(ids))
                current[ids]=raw/raw.sum()*(len(ids)/cfg['top_k'])
            events[i]=True
        weights[i]=current
    out=np.zeros((len(m['dates']),len(names)));event=np.zeros(len(out),bool)
    idx=m['daily_index'];good=idx>=0;out[good]=weights[idx[good]]
    last=m['dates'].hour==20;event[last&good]=events[idx[last&good]]
    out[~m['eligible']]=0
    event[1:] |= np.any(out[1:]!=out[:-1],axis=1)
    return dict(weights=out,event=event)

def benchmark(m):
    j=m['assets'].index('BTCUSDT');s=m['close'].BTCUSDT;regime=(s>s.rolling(200).mean()).to_numpy();idx=m['daily_index']
    w=np.zeros((len(idx),len(m['assets'])));good=idx>=0;w[good,j]=regime[idx[good]];w[~m['eligible']]=0
    e=np.zeros(len(idx),bool);e[1:]=np.any(w[1:]!=w[:-1],axis=1)
    return dict(weights=w,event=e)
