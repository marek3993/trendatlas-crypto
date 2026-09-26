"""Phase-1 event replay with a causal controller seam; default path is byte-for-byte regression checked.
Accounting, fill paths, costs, exposure guards and summary are imported unchanged.
"""
from pathlib import Path
import sys
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'causal_search_20260926'))
import engine as legacy
from engine import State, load_spec, choose_target, mark, exposure, close, trade, emit, path_replay

def simulate(m,p,cap,*,start='2018-08-01',end='2026-09-25',cost_multiplier=1,delay=0,ledger=False,controller=None,resize_enabled=True,cost_overrides=None,signal_lag=2):
    spec,_=load_spec();costs=dict(spec['costs']);costs.update(cost_overrides or {});rate=(costs['fee_bps']+costs['slippage_bps'])*1e-4*cost_multiplier
    funding=costs['funding_annual_debit']*cost_multiplier/365.25
    indices=np.flatnonzero((m.dates>=start)&(m.dates<=end));n=len(indices)
    s=State();rows=np.zeros((n,9));asset_logs=np.zeros((n,len(m.assets)));trade_logs=[];all_events=[];signals=[]
    counters={k:0 for k in ['rotation','stop','partial_tp','exposure_guard','liquidation','gap_cap_breach','no_average_down','reentry_blocked','entries','ambiguous_bars','delayed_entries','expired_entries']}
    for row_i,i in enumerate(indices):
        if m.dates[i].strftime('%m-%d')=='01-01':
            assert not s.qty, 'Annual fold boundary must be flat'
            s.blocked=-1;s.blocked_since=-1;s.cooldown_end=-1
            s.pending_asset=-1
        old_equity=s.equity;events=[];j=i-signal_lag
        if old_equity<=0:
            rows[row_i]=[0,1,1,0,0,0,0,0,0];continue
        target,target_exp=choose_target(m,p,j,s.asset) if controller is None else controller(m,p,j,s,i)[:2]
        can_resize=resize_enabled and (controller is None or controller.resize)
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
            elif s.qty and s.asset==target and can_resize:
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

