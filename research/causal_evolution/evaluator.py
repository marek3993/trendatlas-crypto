"""Only raw own-asset data enter the book. Cached results are this experiment's own."""
import copy
from collections import OrderedDict
import numpy as np
import pandas as pd
from .protocol import CONTRACT, digest, periods
from .vendor import data
from .vendor.common import cid, validate
from .vendor.signals import targets
from .vendor.ledger import replay

def synthetic_market(track, end):
    days=pd.date_range('2019-01-01',end,freq='D');dates=pd.date_range(days[0],days[-1]+pd.Timedelta(hours=20),freq='4h')
    assets=['BTCUSDT','ETHUSDT','ALPHAUSDT','DEADUSDT','NEWUSDT'];t=np.arange(len(dates));n=len(assets)
    p=np.zeros((len(dates),n,5));quote=np.ones((len(dates),n))*4e6
    for a in range(n):
        px=(100+30*a)*np.exp(.00009*t+.18*np.sin(t/(130+10*a)+a)+.06*np.sin(t/(19+a)))
        p[:,a,0]=px;p[:,a,3]=np.r_[px[1:],px[-1]];p[:,a,1]=np.maximum(p[:,a,0],p[:,a,3])*1.003;p[:,a,2]=np.minimum(p[:,a,0],p[:,a,3])*.997;p[:,a,4]=quote[:,a]/px
    dead=t>1100;new=t<700;p[dead,3]=np.nan;quote[dead,3]=np.nan;p[new,4]=np.nan;quote[new,4]=np.nan
    close=pd.DataFrame(p[:,:,3],index=dates,columns=assets).resample('D').last()
    high=pd.DataFrame(p[:,:,1],index=dates,columns=assets).resample('D').max();low=pd.DataFrame(p[:,:,2],index=dates,columns=assets).resample('D').min()
    dailyq=pd.DataFrame(quote,index=dates,columns=assets).resample('D').sum(min_count=6)
    observed=close.notna();liq=dailyq.rolling(30,min_periods=30).mean();base=observed&(observed.cumsum()>=365)&liq.ge(1e7)
    rank=liq.where(base).rank(axis=1,method='first',ascending=False);returns=close.pct_change(fill_method=None)
    funding=[] if track=='spot' else [(date,a,.00002) for date in dates[::2] for a in range(n) if np.isfinite(p[(date-dates[0])//pd.Timedelta(hours=4),a,0])]
    return dict(track=track,assets=assets,days=days,dates=dates,prices=p,quote=quote,mark=p[:,:,:4].copy(),mark_missing=np.zeros(p.shape[:2],bool),funding=funding,close=close,high=high,low=low,base=base,eligible=base&rank.le(5),rank=rank,liquidity=liq,vol=returns.rolling(60).std()*np.sqrt(365.25),daily_returns=returns)

def clean(value):
    if isinstance(value,dict):return {str(k):clean(v) for k,v in value.items()}
    if isinstance(value,(list,tuple)):return [clean(v) for v in value]
    if isinstance(value,(np.integer,)):return int(value)
    if isinstance(value,(float,np.floating)):return float(value) if np.isfinite(value) else None
    if isinstance(value,(np.bool_,)):return bool(value)
    if isinstance(value,pd.Timestamp):return str(value)
    return value

def audit_book(book, market):
    failures=[]
    for f in book['fills']:
        t=pd.Timestamp(f['date']);i=market['dates'].get_indexer([t])[0];a=market['assets'].index(f['asset'])
        if i<0 or not np.isfinite(market['prices'][i,a,0]):failures.append('nonexistent_asset_bar')
        if not np.isclose(f['reference'],market['prices'][i,a,0],rtol=1e-12):failures.append('foreign_asset_price')
        if not t>pd.Timestamp(f['available_at']):failures.append('pre_publication_fill')
        if f['venue']!=market['track']:failures.append('wrong_venue')
    if book['metrics']['log_reconciliation_error']>1e-8:failures.append('account_reconciliation')
    return dict(pass_audit=not failures,failures=sorted(set(failures)),fills_checked=len(book['fills']),
                asset_lineage=market['assets'],track=market['track'],funding='actual_timestamps' if market['track']=='perp' else 'not_applicable')

class Evaluator:
    def __init__(self,store,synthetic=False,guard=None):
        self.store=store;self.synthetic=synthetic;self.guard=guard;self.models={};self.signals=OrderedDict();self.raw={}

    def model(self,track,end):
        key=(track,end)
        if key not in self.models:
            bound=CONTRACT['split']['data_end'] if self.store.meta('outer_opened',False) else max(p['end'] for o in CONTRACT['budget']['outer_origins'] for p in periods(o) if p['scope']!='outer')
            if (track,bound) not in self.raw:
                self.raw.clear();self.models.clear();self.signals.clear()
                self.raw[(track,bound)]=synthetic_market(track,bound) if self.synthetic else data.load(track,bound)
            full=self.raw[(track,bound)];m={};day=pd.Timestamp(end);bar=day+pd.Timedelta(hours=20)
            nd=int((full['days']<=day).sum());nb=int((full['dates']<=bar).sum())
            for k,v in full.items():
                if k.startswith('_'):continue
                if k=='days':m[k]=v[:nd]
                elif k=='dates':m[k]=v[:nb]
                elif k=='funding':m[k]=[(t,a,r) for t,a,r in v if t<day+pd.Timedelta(days=1)]
                elif isinstance(v,pd.DataFrame):m[k]=v.iloc[:nd].copy()
                elif isinstance(v,np.ndarray):m[k]=v[:nb]
                else:m[k]=v
            if len(self.models)>=4:self.models.clear()
            self.models[key]=m
        return self.models[key]

    def evaluate(self,genes,period,track,stress='nominal',capital=100,benchmark=False,cash=False,details=False,schedule=None):
        if period['scope']=='outer' and not self.store.meta('outer_opened',False):raise RuntimeError('Outer is sealed until ALL search freezes')
        genes=validate(genes);request=dict(genes=genes,period=period,track=track,stress=stress,capital=capital,benchmark=benchmark,cash=cash,engine=self.store.meta('fingerprint'),schedule=schedule)
        key=digest(request);cached=self.store.cached(key)
        if cached is not None:return cached
        if self.guard:self.guard(force=True)
        attempt=self.store.reserve(key,period['scope'])
        # Truncate raw observations before constructing signals. No future columns/rows enter training.
        m=self.model(track,period['end']);sigkey=(track,period['end'],cid(genes),benchmark,cash,digest(schedule))
        if sigkey not in self.signals:
            if len(self.signals)>=6:self.signals.popitem(last=False)
            self.signals[sigkey]=(np.zeros_like(m['close'].to_numpy()),np.ones(len(m['days']),bool)) if cash else targets(m,genes,benchmark=benchmark)
        gross_policy=None
        if schedule:
            if benchmark or cash:raise ValueError('Benchmark is a single literal rule')
            w,e=self.signals[sigkey];w=w.copy();e=e.copy();gross_policy=np.ones(len(m['days']))*genes['gross']
            previous_genes=genes
            for step in sorted(schedule,key=lambda x:x['year'])[1:]:
                g=validate(step['genes']);new_w,new_e=targets(m,g)
                if g==previous_genes:continue
                boundary=pd.Timestamp(step['year'],1,1)-pd.Timedelta(days=1)
                change=m['days']>=boundary;w[change]=new_w[change];e[change]=new_e[change];e[m['days']==boundary]=True
                gross_policy[change]=g['gross']
                previous_genes=g
            signal=(w,e)
        else:signal=self.signals[sigkey]
        kw=dict(cost_mult=2.) if stress=='double_cost' else dict(delay=1) if stress=='later_bar' else dict(mark_extra=.03,slip_extra=.002,mm=.20,fund_adverse=track=='perp') if stress=='adverse_mark_fill' else dict(mm=.10) if stress=='maintenance10' else dict(mm=.20) if stress=='maintenance20' else dict(coarse=True) if stress=='coarse_lot' else {}
        # The mandatory literal SMA200 benchmark retains its original unbounded holding rule.
        book=replay(m,signal,period['start'],period['end'],capital=capital,
                    gross_limit=genes['gross'] if track=='perp' and not benchmark else 1.,
                    max_holding_days=None if benchmark or cash or stress=='no_holding_cap' else CONTRACT['split']['max_position_days'],
                    details=True,guard=self.guard,gross_schedule=gross_policy,**kw)
        audit=audit_book(book,m)
        if not audit['pass_audit']:raise AssertionError(audit)
        daily=book['daily'].reset_index();daily['date']=daily['date'].astype(str)
        value=clean(dict(request=request,metrics=book['metrics'],daily=daily.to_dict('records'),episodes=book['episodes'],orders=book['orders'],folds=book['folds'],audit=audit))
        self.store.save(key,attempt,value)
        if details:
            from .protocol import atomic
            atomic(self.store.root/'books'/f'{key}.json',clean(dict(fills=book['fills'],episodes=book['episodes'],orders=book['orders'],audit=audit)))
        return value

def log_returns(value):
    nav=np.array([value['request']['capital']]+[x['nav'] for x in value['daily']])
    return np.log(np.maximum(nav[1:]/nav[:-1],1e-300))

def prefix_audit(genes,track,market,cut,period=None,reference=None):
    """Future mutation must leave every earlier signal byte unchanged."""
    before=targets(market,genes);after=copy.deepcopy(market);boundary=pd.Timestamp(cut)
    for k in ('close','high','low','vol','daily_returns','liquidity','rank'):
        after[k].loc[after[k].index>=boundary]*=17
    for k in ('eligible','base'):after[k].loc[after[k].index>=boundary]=False
    after['funding']=[(t,a,r if t<boundary else r*1000) for t,a,r in after['funding']]
    after.pop('_fund7',None)
    changed=targets(after,genes);ids=market['days']<boundary
    ok=np.array_equal(before[0][ids],changed[0][ids]) and np.array_equal(before[1][ids],changed[1][ids])
    result=dict(candidate=cid(genes),track=track,boundary=cut,pass_audit=bool(ok),days_checked=int(ids.sum()),future_mutation_signals=bool(ok))
    if period is not None and reference is not None:
        nd=int(ids.sum());nb=int((market['dates']<boundary).sum());prefix={}
        for k,v in market.items():
            if k.startswith('_'):continue
            if k=='days':prefix[k]=v[:nd]
            elif k=='dates':prefix[k]=v[:nb]
            elif k=='funding':prefix[k]=[(t,a,r) for t,a,r in v if t<boundary]
            elif isinstance(v,pd.DataFrame):prefix[k]=v.iloc[:nd].copy()
            elif isinstance(v,np.ndarray):prefix[k]=v[:nb]
            else:prefix[k]=v
        prefix_targets=targets(prefix,genes)
        true_prefix=np.array_equal(before[0][:nd],prefix_targets[0]) and np.array_equal(before[1][:nd],prefix_targets[1])
        small=replay(prefix,prefix_targets,period['start'],str((boundary-pd.Timedelta(days=1)).date()),max_holding_days=90,gross_limit=genes['gross'] if track=='perp' else 1.)
        old=[d for d in reference['daily'] if pd.Timestamp(d['date'])<boundary]
        fields=['nav','fee','slippage','funding_debit','funding_credit','residual_usd']
        book_ok=len(old)==len(small['daily']) and np.allclose(np.array([[d[k] for k in fields] for d in old]),small['daily'][fields].to_numpy(),rtol=1e-10,atol=1e-10)
        result.update(true_prefix_signals=bool(true_prefix),true_prefix_ledger=bool(book_ok),pass_audit=bool(ok and true_prefix and book_ok))
    return result
