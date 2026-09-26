"""Causal, deterministic signal controllers. No order/exchange dependencies."""
import numpy as np
from replay import exposure

class Controller:
    def __init__(self,params):
        self.p=params;self.target=-1;self.last_pick=-100000;self.last_year=None;self.resize=False

    def __call__(self,m,p,j,s,i):
        self.resize=False
        if j<0:return -1,0
        f=m.features;c=f['close'][j];btc=m.assets.index('BTC');cfg=self.p
        kind=cfg['family'];n=cfg.get('lookback',90);schedule=cfg.get('schedule','monthly')
        date=m.dates[j];year=m.dates[i].year
        first=self.last_year!=year
        if first:self.target=-1;self.last_pick=-100000;self.last_year=year
        due=first or schedule=='daily' or (schedule=='weekly' and date.dayofweek==6) or (schedule=='monthly' and date.is_month_end)
        eligible=(f['count'][j]>=252)&np.isfinite(c)&np.isfinite(f['vol60'][j])
        if kind=='cash':return -1,0
        if kind=='hold':
            a=m.assets.index(cfg.get('asset','BTC'))
            return (a,1.) if eligible[a] else (-1,0.)
        if kind=='btc_trend':return (btc,1.) if eligible[btc] and c[btc]>f['sma200'][j,btc] else (-1,0.)
        mom=f['mom'+str(n)][j];scores=mom.copy();ok=eligible & np.isfinite(scores)
        if kind in ('dual_momentum','relative_strength','vol_adjusted','slow_hysteresis','simple_momentum'):ok &= mom>0
        if kind=='vol_adjusted':scores=mom/np.maximum(.1,f['vol60'][j])
        if kind=='breakout':ok &= f['breakout'+str(n)][j]
        if kind=='ensemble':
            signals=[f['mom'+str(k)][j] for k in [30,90,180]]
            votes=sum((v>0).astype(int) for v in signals)+(c>f['sma200'][j]).astype(int)
            ranks=[]
            for v in signals:
                ranks.append(np.argsort(np.argsort(np.where(eligible & np.isfinite(v),v,-np.inf))).astype(float))
            scores=np.mean(ranks,axis=0)/len(c);ok &= votes>=3
            scores += .1*f['breakout55'][j]
        if kind=='regime_allocation':
            if not eligible[btc] or c[btc]<=f['sma200'][j,btc]:self.target=-1;return -1,0.
            breadth=float(np.mean((c>f['sma200'][j])[eligible]))
            alt=np.where(ok & (np.arange(len(c))!=btc),mom,-np.inf);a=int(np.argmax(alt))
            target=a if breadth>=.6 and alt[a]>mom[btc]+.10 else btc
        else:
            a=int(np.argmax(np.where(ok,scores,-np.inf)))
            target=a if ok[a] else -1
        # Absolute/trend loss can exit between scheduled rotations; it cannot
        # select a new asset early. Slow holding never overrides a risk exit.
        if self.target>=0 and not ok[self.target]:self.target=-1
        if due:
            held=s.asset
            keep=(kind=='slow_hysteresis' and held>=0 and ok[held] and
                  (i-s.entry_i<cfg.get('min_hold',30) or target>=0 and scores[target]<scores[held]+cfg.get('hysteresis',.10)))
            self.target=held if keep else target
            self.last_pick=i
        a=self.target
        if a<0:return -1,0.
        if kind=='simple_momentum':return a,1.
        target_exp=cfg['vol_target']/max(.1,float(f['vol20'][j,a]))
        ratio=f['vol20'][j,a]/max(.01,float(f['vol60'][j,a]))
        if c[btc]<=f['sma200'][j,btc]:target_exp=min(target_exp,.5)
        if ratio>1.8:target_exp=min(target_exp,.5)
        elif ratio>1.3:target_exp=min(target_exp,.75)
        elif ratio>1.2:target_exp=min(target_exp,1.)
        # Rebalance at the signal cadence, with only material risk reductions
        # between dates. The engine still prohibits adding through a decline.
        self.resize=due or (s.qty>0 and target_exp<.8*exposure(s))
        return a,target_exp
