"""Causal daily event replay. All decisions precede the priced interval.

Linear notional/account equity accounting on explicitly labelled spot/funding
proxies. No production exports or executable exchange clients are dependencies.
"""
from __future__ import annotations
from dataclasses import dataclass, replace
import hashlib
import json
import math
from pathlib import Path
import zipfile
from functools import lru_cache
import numpy as np
import pandas as pd

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]


@lru_cache(maxsize=1)
def load_spec():
    spec=json.loads((HERE/'pre_registration.json').read_text())
    contract=ROOT/spec['contract_path']
    assert hashlib.sha256(contract.read_bytes()).hexdigest()==spec['contract_sha256'], 'Objectives changed since freeze'
    return spec,json.loads(contract.read_text())


@dataclass
class Market:
    dates: pd.DatetimeIndex
    assets: list
    prices: np.ndarray  # day, asset, O/H/L/C
    features: dict


def market_from_frames(frames):
    assets=sorted(frames)
    dates=pd.date_range(min(f.index.min() for f in frames.values()),max(f.index.max() for f in frames.values()),freq='D')
    aligned={a:frames[a].reindex(dates) for a in assets}
    prices=np.stack([aligned[a][['open','high','low','close']].to_numpy(float) for a in assets],axis=1)
    close=pd.DataFrame(prices[:,:,3],index=dates,columns=assets)
    ret=close.pct_change(fill_method=None)
    feat={'count':close.notna().cumsum().to_numpy(), 'close':close.to_numpy(),
          'rebound':((close>close.shift(1))&(close.shift(1)>close.shift(2))&(close>close.ewm(span=20,adjust=False).mean())).to_numpy()}
    for n in [20,60]: feat[f'vol{n}']=ret.rolling(n,min_periods=n).std(ddof=1).to_numpy()*np.sqrt(365.25)
    for n in [20,100,200]: feat[f'ema{n}']=close.ewm(span=n,adjust=False,min_periods=n).mean().to_numpy()
    for n in [21,63,126]: feat[f'mom{n}']=(close/close.shift(n)-1).to_numpy()
    atr=[]
    for a in assets:
        f=aligned[a];prior=f.close.shift(1)
        tr=pd.concat([f.high-f.low,(f.high-prior).abs(),(f.low-prior).abs()],axis=1).max(axis=1)
        atr.append(tr.ewm(alpha=1/14,adjust=False,min_periods=14).mean().to_numpy())
    feat['atr']=np.array(atr).T
    return Market(dates,assets,prices,feat)


def load_market():
    spec,_=load_spec();bundle=HERE/'inputs.zip'
    assert hashlib.sha256(bundle.read_bytes()).hexdigest()==spec['input_bundle_sha256']
    frames={}
    with zipfile.ZipFile(bundle) as z:
        assert set(z.namelist())==set(spec['input_members'])
        for identity in spec['identity']:
            name=identity['member'];raw=z.read(name)
            assert hashlib.sha256(raw).hexdigest()==spec['input_members'][name]
            f=pd.read_csv(z.open(name),parse_dates=['date']).set_index('date').sort_index()
            assert f.index.is_unique and f.index.equals(pd.date_range(f.index[0],f.index[-1])),f'Gaps: {name}'
            assert np.isfinite(f[['open','high','low','close']]).all().all(),name
            assert (f[['open','high','low','close']]>0).all().all(),name
            assert (f.high>=f[['open','close','low']].max(axis=1)).all(),name
            assert (f.low<=f[['open','close','high']].min(axis=1)).all(),name
            assert identity['symbol']==identity['asset']+'USDT' and name==identity['symbol']+'_1d.csv'
            frames[identity['asset']]=f
    return market_from_frames(frames)


@dataclass
class State:
    equity: float=1.0
    qty: float=0.0
    asset: int=-1
    mark: float=0.0
    entry: float=0.0
    entry_atr: float=0.0
    entry_i: int=-1
    last_add: float=0.0
    high_water: float=0.0
    trail: float=0.0
    tp_done: bool=False
    episode: int=0
    blocked: int=-1
    blocked_since: int=-1
    cooldown_end: int=-1
    bankrupt: bool=False
    pending_asset: int=-1
    pending_exposure: float=0.0
    pending_due: int=-1
    pending_source: int=-1


def emit(s, events, before, kind, price=0, qty=0, cost=0, turnover=0):
    growth=math.log(s.equity/before) if before>0 and s.equity>0 else -1000.0
    events.append((s.asset,s.episode,growth,cost/max(before,1e-100),turnover/max(before,1e-100),kind,price,qty,s.equity))


def mark(s,p,events):
    if not s.qty: return
    old=s.equity;s.equity+=s.qty*(p-s.mark);s.mark=p
    if s.equity<=0: s.equity=0;s.bankrupt=True
    emit(s,events,old,'mark',p)


def trade(s,delta,p,rate,events,kind):
    old=s.equity;notional=abs(delta)*p;cost=notional*rate
    s.equity=max(0,s.equity-cost);s.qty=max(0,s.qty+delta)
    if s.equity==0: s.bankrupt=True
    emit(s,events,old,kind,p,delta,cost,notional)


def close(s,p,rate,events,kind,i,cooldown):
    if not s.qty:return
    trade(s,-s.qty,p,rate,events,kind)
    if kind in ('stop','exposure_guard','liquidation'):
        s.blocked=s.asset;s.blocked_since=i;s.cooldown_end=i+cooldown
    s.qty=0;s.asset=-1


def exposure(s):
    return s.qty*s.mark/s.equity if s.equity>0 else (1e6 if s.qty else 0)


def exposure_trigger(s,cap):
    # qP/(E + q(P - mark)) = cap. Only a leveraged long can hit the
    # upper exposure limit during a continuous price decline.
    if not s.qty or cap<=1 or exposure(s)<=1:return 0.0
    return max(0,cap*(s.qty*s.mark-s.equity)/(s.qty*(cap-1)))


def path_replay(state, nodes, p, cap, rate, i):
    s=replace(state);events=[];max_exp=exposure(s);reasons=[]
    for node in nodes:
        if not s.qty:break
        if node<s.mark:
            catastrophic=s.entry-p['catastrophic']*s.entry_atr if p['catastrophic'] else 0
            limit=exposure_trigger(s,cap)
            levels=[(max(catastrophic,s.trail),'stop'),(limit,'exposure_guard')]
            trigger,kind=max(levels)
            if trigger>0 and node<=trigger<=s.mark:
                mark(s,trigger,events);max_exp=max(max_exp,exposure(s))
                close(s,trigger,rate,events,kind,i,p['cooldown']);reasons.append(kind);break
        elif node>s.mark and p['tp'] and not s.tp_done:
            trigger=s.entry+p['tp_atr']*s.entry_atr
            if s.mark<=trigger<=node:
                mark(s,trigger,events);max_exp=max(max_exp,exposure(s))
                trade(s,-s.qty*p['tp'],trigger,rate,events,'partial_tp');s.tp_done=True;reasons.append('partial_tp')
        mark(s,node,events);max_exp=max(max_exp,exposure(s))
        if s.bankrupt:
            s.qty=0;s.asset=-1;break
    return s,events,max_exp,reasons


def choose_target(m,p,j,held):
    if j<0:return -1,0
    f=m.features;mom=f['mom'+str(p['momentum'])][j];c=f['close'][j]
    ema=f['ema100' if p['trend']=='own100' else 'ema200'][j]
    ok=(f['count'][j]>=252)&(c>ema)&(mom>0)&np.isfinite(f['vol20'][j])
    btc=m.assets.index('BTC')
    btc_good=c[btc]>f['ema200'][j,btc]
    if p['trend']=='market200' and not btc_good:return -1,0
    scores=np.where(ok,mom,-np.inf)
    a=int(np.argmax(scores))
    if not np.isfinite(scores[a]):return -1,0
    if held>=0 and ok[held] and scores[a]<=scores[held]*1.05:a=held
    sigma=max(.10,float(f['vol20'][j,a]));target=p['vol_target']/sigma
    ratio=f['vol20'][j,a]/max(.01,f['vol60'][j,a])
    if not btc_good:target=min(target,.5)
    elif ratio>1.8:target=min(target,.5)
    elif ratio>1.3:target=min(target,.75)
    if ratio>1.2:target=min(target,1.0)
    return a,target


def simulate(m,p,cap,*,start='2018-08-01',end='2026-09-25',cost_multiplier=1,delay=0,ledger=False):
    spec,_=load_spec();costs=spec['costs'];rate=(costs['fee_bps']+costs['slippage_bps'])*1e-4*cost_multiplier
    funding=costs['funding_annual_debit']*cost_multiplier/365.25
    indices=np.flatnonzero((m.dates>=start)&(m.dates<=end));n=len(indices)
    s=State();rows=np.zeros((n,9));asset_logs=np.zeros((n,len(m.assets)));trade_logs=[];all_events=[];signals=[]
    counters={k:0 for k in ['rotation','stop','partial_tp','exposure_guard','liquidation','gap_cap_breach','no_average_down','reentry_blocked','entries','ambiguous_bars','delayed_entries','expired_entries']}
    for row_i,i in enumerate(indices):
        if m.dates[i].strftime('%m-%d')=='01-01':
            assert not s.qty, 'Annual fold boundary must be flat'
            s.blocked=-1;s.blocked_since=-1;s.cooldown_end=-1
            s.pending_asset=-1
        old_equity=s.equity;events=[];j=i-2
        if old_equity<=0:
            rows[row_i]=[0,1,1,0,0,0,0,0,0];continue
        target,target_exp=choose_target(m,p,j,s.asset)
        target_exp=min(cap*.9,target_exp)
        signals.append((str(m.dates[i].date()),str(m.dates[j].date()) if j>=0 else '',target,target_exp))
        day_max=0;did_exit=False;rotation=False;old_asset=s.asset;opening_reference=s.mark
        if s.qty:
            opening=m.prices[i,s.asset,0]
            if not np.isfinite(opening):raise ValueError('Missing held price')
            mark(s,opening,events);day_max=exposure(s)
            if day_max>cap+1e-9:counters['gap_cap_breach']+=1
            if s.bankrupt:
                s.qty=0;s.asset=-1
            elif s.equity<=costs['maintenance_ratio']*s.qty*s.mark:
                close(s,opening,rate+costs['liquidation_fee_bps']*1e-4,events,'liquidation',i,p['cooldown'])
                counters['liquidation']+=1;did_exit=True
            elif target!=s.asset:
                close(s,opening,rate,events,'rotation',i,0);counters['rotation']+=1;did_exit=True
            else:
                if j>=s.entry_i and p['trail']:
                    s.high_water=max(s.high_water,float(m.prices[j,s.asset,1]))
                    if s.high_water>=s.entry+s.entry_atr:
                        s.trail=max(s.trail,s.high_water-p['trail']*m.features['atr'][j,s.asset])
                catastrophe=s.entry-p['catastrophic']*s.entry_atr if p['catastrophic'] else 0
                reason='exposure_guard' if exposure(s)>cap else 'stop'
                if opening<=max(catastrophe,s.trail) or exposure(s)>cap:
                    close(s,opening,rate,events,reason,i,p['cooldown']);counters[reason]+=1;did_exit=True
        if not s.bankrupt and target>=0:
            price=m.prices[i,target,0]
            if not np.isfinite(price):raise ValueError('Missing target price')
            rotation=target!=old_asset and old_asset>=0
            if rotation:s.blocked=-1;s.blocked_since=-1;s.cooldown_end=-1
            # Two rising completed closes must occur after the risk exit, even
            # in the zero-cooldown control. A pre-exit rebound is not reentry
            # evidence. Normal rotation to a new target keeps its priority.
            blocked=(target==s.blocked and (i<=s.cooldown_end or j<s.blocked_since+2 or not m.features['rebound'][j,target]))
            if not s.qty and not (did_exit and not rotation) and not blocked:
                entry_source=j;entry_exposure=target_exp;ready=not delay
                if delay:
                    if s.pending_asset>=0 and s.pending_asset!=target:
                        counters['expired_entries']+=1;s.pending_asset=-1
                    if s.pending_asset==target and s.pending_due<=i:
                        entry_source=s.pending_source;entry_exposure=s.pending_exposure;ready=True
                        counters['delayed_entries']+=1
                    elif s.pending_asset<0:
                        s.pending_asset=target;s.pending_exposure=target_exp;s.pending_due=i+delay;s.pending_source=j
                if ready:
                    s.asset=target;s.mark=price;s.entry=price;s.last_add=price;s.entry_atr=float(m.features['atr'][entry_source,target])
                    s.entry_i=i;s.high_water=price;s.trail=0;s.tp_done=False;s.episode+=1
                    qty=entry_exposure*s.equity/(price*(1+entry_exposure*rate))
                    trade(s,qty,price,rate,events,'entry');counters['entries']+=1;s.pending_asset=-1
                    signals[-1]=(str(m.dates[i].date()),str(m.dates[entry_source].date()),target,entry_exposure)
            elif blocked and not s.qty:counters['reentry_blocked']+=1
            elif s.qty and s.asset==target:
                wanted=target_exp*s.equity/(price*(1+target_exp*rate))
                change=wanted-s.qty
                if change>0 and (s.tp_done or price<s.last_add or price<opening_reference or not m.features['rebound'][j,target]):
                    counters['no_average_down']+=1
                elif abs(change)*price/max(s.equity,1e-100)>.01:
                    trade(s,change,price,rate,events,'resize')
                    if change>0:s.last_add=price
        if target<0 or did_exit and not rotation:
            if s.pending_asset>=0:counters['expired_entries']+=1
            s.pending_asset=-1
        day_max=max(day_max,exposure(s))
        # Declared conservative daily funding proxy: full opening held notional
        # is debited before the intraday path, even if stopped later that day.
        if s.qty:
            before=s.equity;charge=s.qty*s.mark*funding;s.equity=max(0,s.equity-charge)
            emit(s,events,before,'funding',s.mark,cost=charge)
            day_max=max(day_max,exposure(s))
            if exposure(s)>cap+1e-9:
                close(s,s.mark,rate,events,'exposure_guard',i,p['cooldown']);counters['exposure_guard']+=1
        if s.qty:
            o,h,l,c=m.prices[i,s.asset]
            a=path_replay(s,[h,l,c],p,cap,rate,i);b=path_replay(s,[l,h,c],p,cap,rate,i)
            if abs(a[0].equity-b[0].equity)>1e-12:counters['ambiguous_bars']+=1
            # O-H-L-C wins ties: conservative peak-before-trough drawdown.
            chosen=a if a[0].equity<=b[0].equity else b
            s,more,mx,reasons=chosen;events.extend(more);day_max=max(day_max,mx)
            for reason in reasons:counters[reason]+=1
        # Predeclared annual boundaries avoid hidden carry across fold choices.
        if s.qty and (m.dates[i].strftime('%m-%d')=='12-31' or row_i==n-1):
            close(s,s.mark,rate,events,'boundary_exit',i,0)
        equity_events=np.array([old_equity]+[e[8] for e in events]+[s.equity])
        internal_dd=float(np.max(1-equity_events/np.maximum.accumulate(equity_events)))
        rows[row_i]=[s.equity/old_equity-1,equity_events.min()/old_equity,equity_events.max()/old_equity,internal_dd,
                     sum(e[4] for e in events),sum(e[3] for e in events),day_max,float(s.bankrupt),float(bool(events))]
        per_episode={}
        for e in events:
            a,ep,growth=e[:3]
            if a>=0:asset_logs[row_i,a]+=growth
            per_episode[(a,ep)]=per_episode.get((a,ep),0)+growth
            if ledger:all_events.append((str(m.dates[i].date()),m.assets[a] if a>=0 else 'CASH',ep,*e[2:]))
        for (a,ep),growth in per_episode.items():trade_logs.append((row_i,a,ep,growth))
    return dict(dates=m.dates[indices],rows=rows,asset_logs=asset_logs,trade_logs=np.array(trade_logs).reshape(-1,4),
                events=all_events,signals=signals,counters=counters,params=p,cap=cap)


def summarize(run,start=None,end=None):
    dates=run['dates'];mask=np.ones(len(dates),dtype=bool)
    if start:mask&=dates>=start
    if end:mask&=dates<=end
    ids=np.flatnonzero(mask);r=run['rows'][mask];rets=r[:,0];n=len(r)
    if not n:raise ValueError('Empty metric interval')
    years=((dates[ids[-1]]-dates[ids[0]]).days+1)/365.25
    equity=np.r_[1,np.cumprod(1+rets)];logs=np.log1p(np.maximum(rets,-1+1e-15));total=float(logs.sum())
    cagr=float(equity[-1]**(1/years)-1)
    peak=1.;dd=0.
    for k,row in enumerate(r):
        dd=max(dd,1-equity[k]*row[1]/peak,row[3]);peak=max(peak,equity[k]*row[2])
    trades=run['trade_logs'];trades=trades[(trades[:,0]>=ids[0])&(trades[:,0]<=ids[-1])] if len(trades) else trades
    groups={}
    for _,_,ep,g in trades:groups[int(ep)]=groups.get(int(ep),0.)+g
    best=sorted((x for x in groups.values() if x>0),reverse=True)
    asset=run['asset_logs'][mask].sum(axis=0)
    share=lambda x:float(max(0,max(x,default=0))/total) if total>0 else 1e6
    std=np.std(rets,ddof=1) if n>1 else 0
    return dict(cagr=cagr,max_drawdown=float(dd),calmar=float(cagr/dd) if dd>0 else 0.,
        sharpe=float(np.mean(rets)/std*np.sqrt(365.25)) if std>0 else 0.,total_return=float(equity[-1]-1),
        turnover=float(r[:,4].sum()/years),cost_drag=float(r[:,5].sum()/years),max_realized_exposure=float(r[:,6].max()),
        without_best_day_cagr=float(math.exp((total-max(0,logs.max()))/years)-1),
        without_top_three_trades_cagr=float(math.exp((total-sum(best[:3]))/years)-1),
        asset_log_growth_share=share(asset),trade_log_growth_share=share(best),
        net_log_growth=total,asset_log_growth=asset.tolist(),trade_log_growth_sum=float(sum(groups.values())),
        log_reconciliation_error=float(abs(asset.sum()-total)),trade_log_reconciliation_error=float(abs(sum(groups.values())-total)),
        bankrupt=bool(r[:,7].max()),days=n,closed_episodes=len(groups))


def stitch(runs):
    result=dict(dates=runs[0]['dates'].append([x['dates'] for x in runs[1:]]),rows=np.concatenate([x['rows'] for x in runs]),
                asset_logs=np.concatenate([x['asset_logs'] for x in runs]),trade_logs=[],events=[],signals=[],counters={})
    offset=0
    for k,run in enumerate(runs):
        a=run['trade_logs'].copy()
        if len(a):a[:,0]+=offset;a[:,2]+=(k+1)*1000000
        result['trade_logs'].append(a);offset+=len(run['dates'])
        result['events']+=run['events'];result['signals']+=run['signals']
        for name,count in run['counters'].items():result['counters'][name]=result['counters'].get(name,0)+count
    result['trade_logs']=np.concatenate(result['trade_logs'])
    return result
