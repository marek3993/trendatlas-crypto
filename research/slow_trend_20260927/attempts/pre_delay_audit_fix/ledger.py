"""Asset-resolved cash/quantity ledger descended from archaeology invariants.

No return-stream input. Linear perp collateral accounting is algebraically cash
plus signed quantities at own mark, with funding as separate cash transactions.
"""
import math
import numpy as np
import pandas as pd
from common import SPEC

def summary(daily,initial,mdd=None):
    nav=np.r_[initial,daily.nav.to_numpy()];r=nav[1:]/nav[:-1]-1
    years=len(daily)/365.25
    dd=float(np.max(1-nav/np.maximum.accumulate(nav))) if len(nav) else 0
    if 'nav_high' in daily:
        highs=np.maximum.accumulate(np.r_[initial,daily.nav_high.to_numpy()])[1:]
        dd=max(dd,float(np.max(1-daily.nav_low.to_numpy()/highs)))
    dd=max(dd,mdd or 0);cagr=float((nav[-1]/initial)**(1/years)-1) if nav[-1]>0 and years else -1.
    sd=float(np.std(r,ddof=1)) if len(r)>1 else 0
    sharpe=float(np.mean(r)/sd*np.sqrt(365.25)) if sd>1e-14 else 0
    return dict(cagr=cagr,mdd=dd,sharpe=sharpe,calmar=cagr/dd if dd>1e-12 else 0,final_nav=float(nav[-1]))

def replay(m,targets,start,end,capital=100.,cost_mult=1.,delay=0,mm=.05,mark_extra=0.,fund_adverse=False,coarse=False,overlay='none',details=False,gross_limit=1.0):
    W,E=targets;dates=m['dates'];P=m['prices'];M=m['mark'];N=len(m['assets']);names=m['assets'];perp=m['track']=='perp'
    inds=np.flatnonzero((dates>=pd.Timestamp(start))&(dates<pd.Timestamp(end)+pd.Timedelta(days=1)))
    if not len(inds):raise ValueError('Empty evaluation period')
    q=np.zeros(N);mark=np.zeros(N);cash=float(capital);pending=np.full(N,np.nan);expiry=np.zeros(N,int);order_start=np.zeros(N,int);signal_day=np.zeros(N,int);order_qty=np.zeros(N);order_fill=np.zeros(N);order_value=np.zeros(N)
    stale=np.zeros(N,int);open_ep=[None]*N;episodes=[];fills=[];orders=[];barrows=[];logs=np.zeros((len(inds),N));qrows=[];last_intent=np.zeros(N)
    last_funding=np.full(N,-999999);fund_map={}
    available=[None]*N;signal_kind=['strategy']*N;risk_marks=np.zeros(N);emergency_due=None;emergency_available=None
    for t,j,r in m['funding']:
        k=int((t-dates[0])/pd.Timedelta(hours=4));fund_map.setdefault(k,[]).append((t,j,r))
        if k<inds[0]:last_funding[j]=max(last_funding[j],k)
    fee_rate=(SPEC['execution']['perp_fee_bps'] if perp else SPEC['execution']['spot_fee_bps'])*1e-4*cost_mult;slip=SPEC['execution']['slippage_bps']*1e-4*cost_mult
    peak=capital;mdd=0.;flags=set();serial=0;max_stale=0;min_margin=1e9;ep_entry=np.zeros(N);ep_high=np.zeros(N);tp_done=np.zeros(N,bool);stopped=np.zeros(N,bool)
    total_requested=0.;total_filled=0.;ttl_count=0;partial_count=0;minimum_rejections=0;episode_logs={}
    gross_cap=float(gross_limit) if perp else 1.0
    if gross_cap not in [1.0,1.25]:raise ValueError('Frozen gross limits only')
    def nav():return float(cash+q@mark)
    def allocate(changes):
        # Exact telescoping account log attribution, asset-specific dollar causes.
        before=nav();total=float(np.sum(changes));after=before+total
        if before<=0 or after<=0:flags.add('bankruptcy');return
        factor=math.log(after/before)/total if abs(total)>1e-12 else 1/before
        logs[bi]+=np.asarray(changes)*factor
        for a in np.flatnonzero(np.abs(changes)>0):
            if open_ep[a] is not None:
                open_ep[a]['log_growth']+=float(changes[a]*factor);open_ep[a]['pnl_usd']+=float(changes[a])
                key=(open_ep[a]['id'],bi);episode_logs[key]=episode_logs.get(key,0.)+float(changes[a]*factor)
    def move(new):
        nonlocal mark
        good=np.isfinite(new)&(new>0);nm=np.where(good,new,mark);allocate(q*(nm-mark));mark=nm
    def cancel(a,reason):
        if np.isfinite(pending[a]):
            orders.append(dict(asset=names[a],submitted=str(dates[order_start[a]]),ended=str(date),reason=reason,target_quantity=float(pending[a]),filled_quantity=float(order_fill[a]),average_price=float(order_value[a]/abs(order_fill[a])) if order_fill[a] else None,unfilled_quantity=float(pending[a]-q[a])))
        pending[a]=np.nan
    def funding_event(a,rate):
        nonlocal cash,fund_debit,fund_credit
        if not q[a]:return
        value=-q[a]*mark[a]*rate
        if value<0:value*=cost_mult;fund_debit-=value
        else:
            if fund_adverse:value=0.
            fund_credit+=value
        changes=np.zeros(N);changes[a]=value;allocate(changes);cash+=value
    def fill(a,delta,reference):
        nonlocal cash,serial,fees,slippage,turn_usd,turn_nav,total_filled,partial_count
        old=q[a];execution=reference*(1+np.sign(delta)*slip);fee=abs(delta)*execution*fee_rate;slippage_cost=abs(delta)*abs(execution-reference)
        if not old:
            serial+=1;open_ep[a]=dict(id=serial,asset=names[a],side='long' if delta>0 else 'short',entry=str(date),log_growth=0.,pnl_usd=0.,closed=False);ep_entry[a]=execution;ep_high[a]=execution;tp_done[a]=False
        before=nav();changes=np.zeros(N);changes[a]=delta*(mark[a]-execution)-fee;allocate(changes)
        cash-=delta*execution+fee;q[a]+=delta
        fees+=fee;slippage+=slippage_cost;turn_usd+=abs(delta)*execution;turn_nav+=abs(delta)*execution/max(before,1e-12)
        order_fill[a]+=delta;order_value[a]+=abs(delta)*execution;total_filled+=abs(delta)*execution
        if abs(q[a])<1e-12:q[a]=0.
        if details:fills.append(dict(date=str(date),asset=names[a],venue=m['track'],quantity=float(delta),reference=float(reference),price=float(execution),fee=float(fee),slippage=float(slippage_cost),signal_day=str(m['days'][signal_day[a]]),signal_kind=signal_kind[a],available_at=str(available[a]),lagged_quote=float(m['quote'][i-2,a]),episode=open_ep[a]['id']))
        if q[a]==0 and open_ep[a] is not None:
            ep=open_ep[a];ep.update(exit=str(date),closed=True,holding_days=float((date-pd.Timestamp(ep['entry']))/pd.Timedelta(days=1)));episodes.append(ep);open_ep[a]=None
        if np.isfinite(pending[a]) and abs(pending[a]-q[a])>1e-10:partial_count+=1
    for bi,i in enumerate(inds):
        date=dates[i];fees=slippage=fund_debit=fund_credit=turn_usd=turn_nav=0.
        move(M[i,:,0]);held=np.abs(q)>1e-12;stale=np.where(held&~np.isfinite(M[i,:,0]),stale+1,0);max_stale=max(max_stale,int(stale.max()))
        if np.any(stale>6):flags.add('held_price_stale_over24h')
        # A funding event exactly at open belongs to quantities before our fill.
        for t,a,r in fund_map.get(i,[]):
            if t<=date:funding_event(a,r);last_funding[a]=i
        j=i-2-delay;day=j//6
        daily_event=j>=0 and j%6==5 and day<len(W)
        overlay_changed=False
        if daily_event and overlay!='none':
            before_overlay=(stopped.copy(),tp_done.copy())
            for a in np.flatnonzero(q>0):
                px=float(m['close'].iloc[day,a]);ep_high[a]=max(ep_high[a],float(m['high'].iloc[day,a]))
                stop=(overlay=='fixed_stop20' and px<.8*ep_entry[a]) or (overlay=='trailing25' and px<.75*ep_high[a])
                if stop:stopped[a]=True
                if overlay=='partial_tp50' and px>=1.5*ep_entry[a]:tp_done[a]=True
            stopped[W[day]<=0]=False
            overlay_changed=bool(np.any(stopped!=before_overlay[0]) or np.any(tp_done!=before_overlay[1]))
        action=daily_event and (E[day] or bi<=3 or overlay_changed)
        if action:
            w=W[day].copy()
            if not perp and (np.any(w<0) or np.abs(w).sum()>1.0000001):raise AssertionError('Spot cannot borrow/short')
            if perp and np.abs(w).sum()>1.2500001:raise AssertionError('Gross target exceeds frozen cap')
            # Optional overlays use ONLY the last completed daily observations.
            if overlay!='none':
                w[stopped]=0;w[tp_done]*=.5
            if emergency_due is not None and i>=emergency_due:w[:]=0
            eq=nav();last_intent=w.copy()
            for a in range(N):
                if not (w[a] or q[a] or np.isfinite(pending[a])):continue
                cancel(a,'new_intent');ref=P[i,a,0] if np.isfinite(P[i,a,0]) and P[i,a,0]>0 else mark[a]
                if ref<=0:continue
                target=w[a]*eq/ref
                quantum=1/ref if coarse else 1e-8
                target=np.sign(target)*math.floor(abs(target)/quantum+1e-8)*quantum
                if abs(target-q[a])*ref<1e-7:continue
                pending[a]=target;order_start[a]=i;signal_day[a]=day;order_qty[a]=target-q[a];order_fill[a]=order_value[a]=0
                available[a]=m['days'][day]+pd.Timedelta(days=1,seconds=60);signal_kind[a]='strategy'
                reduction=q[a]!=0 and (target*q[a]<=0 or abs(target)<abs(q[a]))
                expiry[a]=i+(18 if reduction else 6);total_requested+=abs(target-q[a])*ref
        # A fixed gross exposure cap is a safety constraint, not free daily alpha.
        known=M[max(0,i-2),:,3];risk_marks=np.where(np.isfinite(known)&(known>0),known,risk_marks)
        eq_known=float(cash+q@risk_marks);gross_known=float(np.abs(q*risk_marks).sum());cap=gross_cap
        if perp and gross_known>cap*max(eq_known,0)*1.02 and eq_known>0:
            scale=cap*eq_known/gross_known
            for a in np.flatnonzero(q):
                if not np.isfinite(pending[a]):
                    pending[a]=q[a]*scale;order_start[a]=i;signal_day[a]=max(0,(i-2)//6);expiry[a]=i+18;order_fill[a]=order_value[a]=0
                    available[a]=dates[max(0,i-2)]+pd.Timedelta(hours=4,seconds=60);signal_kind[a]='published_4h_gross_risk'
        if emergency_due is not None and i>=emergency_due:
            last_intent[:]=0
            for a in np.flatnonzero(q):
                if np.isfinite(pending[a]) and pending[a]==0:continue
                cancel(a,'published_margin_risk');pending[a]=0.;order_start[a]=i;signal_day[a]=max(0,(i-2)//6);expiry[a]=i+18;order_fill[a]=order_value[a]=0
                available[a]=emergency_available;signal_kind[a]='published_4h_margin_risk'
        for a in np.flatnonzero(np.isfinite(pending)):
            if i>=expiry[a]:ttl_count+=1;cancel(a,'TTL_residual_kept')
        capacities=np.where(np.isfinite(m['quote'][max(0,i-2)]),m['quote'][max(0,i-2)]*.001,0.)
        # Reductions first; a sign reversal is two actual fills, hence two episodes.
        for reducing in [True,False]:
            for a in np.flatnonzero(np.isfinite(pending)):
                ref=P[i,a,0]
                if not np.isfinite(ref) or ref<=0 or not np.isfinite(P[i,a,4]) or P[i,a,4]<=0:continue
                delta=pending[a]-q[a]
                if abs(delta)<1e-12:cancel(a,'filled');continue
                isreduce=q[a]!=0 and delta*q[a]<0
                if reducing!=isreduce:continue
                if isreduce:delta=np.sign(delta)*min(abs(delta),abs(q[a]))
                requested=abs(delta)*ref
                if requested<10-1e-7:minimum_rejections+=1;continue
                amount=min(requested,capacities[a]);delta=np.sign(delta)*amount/ref
                if amount<1e-8:continue
                if not reducing:
                    if perp:
                        room=max(0,cap*nav()-np.abs(q*mark).sum());delta=np.sign(delta)*min(abs(delta),room/(ref*(1+cap*(fee_rate+slip))))
                    else:delta=min(delta,max(0,cash)/(ref*(1+slip)*(1+fee_rate)))
                if abs(delta)*ref<1e-8:continue
                fill(a,delta,ref);capacities[a]-=abs(delta)*ref
                if abs(pending[a]-q[a])*ref<1e-7:cancel(a,'filled')
        for t,a,r in fund_map.get(i,[]):
            if t>date:funding_event(a,r);last_funding[a]=i
        if perp:
            if np.any((np.abs(q)>1e-12)&(i-last_funding>4)):flags.add('held_funding_gap_over16h')
            if fund_adverse:
                charge=np.abs(q*mark)*.1/(365.25*6);allocate(-charge);cash-=float(charge.sum());fund_debit+=float(charge.sum())
        eq=nav();adverse=np.where(q>=0,M[i,:,2]*(1-mark_extra),M[i,:,1]*(1+mark_extra));favorable=np.where(q>=0,M[i,:,1],M[i,:,2]);adverse=np.where(np.isfinite(adverse),adverse,mark);favorable=np.where(np.isfinite(favorable),favorable,mark)
        worst=float(eq+q@(adverse-mark));best=float(eq+q@(favorable-mark));peak=max(peak,best,eq);mdd=max(mdd,1-worst/peak if peak>0 else 1)
        if perp and np.any(q):
            maintenance=mm*float(np.abs(q*adverse).sum());ratio=worst/maintenance if maintenance>0 else 1e9;min_margin=min(min_margin,ratio)
            if ratio<3:
                flags.add('margin_proximity')
                if emergency_due is None:emergency_due=i+2+delay;emergency_available=date+pd.Timedelta(hours=4,seconds=60)
            if ratio<=1:flags.add('proxy_liquidation_breach')
        move(M[i,:,3]);eq=nav();peak=max(peak,eq)
        if eq<=0:flags.add('bankruptcy')
        residual=np.where((last_intent==0)&(np.abs(q)>1e-12),np.abs(q*mark),0)
        stale_exit=(last_intent==0)&(np.abs(q*mark)>=10)&(i-order_start>18)
        if float(np.abs(q[stale_exit]*mark[stale_exit]).sum())>max(10,.10*max(eq,0)):flags.add('material_exit_over72h')
        barrows.append(dict(date=date,nav=eq,nav_high=max(best,eq),nav_low=min(worst,eq),fee=fees,slippage=slippage,funding_debit=fund_debit,funding_credit=fund_credit,turnover=turn_nav,traded_usd=turn_usd,gross=float(np.abs(q*mark).sum()/max(eq,1e-12)),net=float(q@mark/max(eq,1e-12)),residual_usd=float(residual.sum()),mark_proxy_usd=float(np.abs(q[m['mark_missing'][i]]*mark[m['mark_missing'][i]]).sum()) if perp else 0.,intrabar_mdd=mdd))
        if details:qrows.append(q.copy())
    for a in range(N):
        cancel(a,'evaluation_end_residual_kept')
        if open_ep[a] is not None:
            ep=open_ep[a];ep.update(exit=None,holding_days=float((dates[inds[-1]]+pd.Timedelta(hours=4)-pd.Timestamp(ep['entry']))/pd.Timedelta(days=1)),quantity=float(q[a]),mark=float(mark[a]),notional_usd=float(q[a]*mark[a]));episodes.append(ep)
    bars=pd.DataFrame(barrows).set_index('date');daily=bars.resample('D').agg({'nav':'last','nav_high':'max','nav_low':'min','fee':'sum','slippage':'sum','funding_debit':'sum','funding_credit':'sum','turnover':'sum','traded_usd':'sum','gross':'mean','net':'mean','residual_usd':'last','mark_proxy_usd':'mean','intrabar_mdd':'max'})
    stats=summary(daily,capital,mdd);years=len(daily)/365.25;closed=[e for e in episodes if e['closed']];profit=np.array([max(0,e['pnl_usd']) for e in episodes]);byasset={a:sum(max(0,e['pnl_usd']) for e in episodes if e['asset']==a) for a in names}
    stats.update(reliable=not flags,flags=sorted(flags),turnover=float(daily.turnover.sum()/years),fee_usd=float(daily.fee.sum()),slippage_usd=float(daily.slippage.sum()),funding_debit_usd=float(daily.funding_debit.sum()),funding_credit_usd=float(daily.funding_credit.sum()),costs_usd=float((daily.fee+daily.slippage+daily.funding_debit-daily.funding_credit).sum()),exposure=float(daily.gross.mean()),net_exposure=float(daily.net.mean()),trades=len(closed),open_episodes=len(episodes)-len(closed),median_holding_days=float(np.median([e['holding_days'] for e in closed])) if closed else 0.,residual_usd=float(daily.residual_usd.iloc[-1]),max_residual_usd=float(daily.residual_usd.max()),asset_concentration=max(byasset.values())/sum(byasset.values()) if sum(byasset.values()) else None,episode_concentration=float(profit.max()/profit.sum()) if profit.sum() else None,minimum_margin_multiple=min_margin if perp else None,max_stale_bars=max_stale,ttl_cancellations=ttl_count,partial_fills=partial_count,minimum_order_deferrals=minimum_rejections,requested_usd=total_requested,filled_usd=total_filled,mark_proxy_usd_days=float(daily.mark_proxy_usd.sum()))
    # Sensitivity removes whole exact account-log contributions; it is not an executable alternate strategy.
    navs=np.r_[capital,daily.nav.to_numpy()];rets=navs[1:]/navs[:-1]-1;lr=np.log(np.maximum(1+rets,1e-300));nb=lr.copy();nb[int(np.argmax(lr))]=0
    stats['no_best_day_cagr']=float(np.exp(nb.sum()/years)-1)
    winners=sorted(closed,key=lambda e:e['log_growth'],reverse=True)[:3];remove=sum(max(0,e['log_growth']) for e in winners)
    stats['no_top3_cagr']=float(np.exp((lr.sum()-remove)/years)-1);stats['removed_episode_ids']=[e['id'] for e in winners if e['log_growth']>0]
    removed_set=set(stats['removed_episode_ids']);remain_log=np.zeros(len(inds))
    # Reconstruct removed episode spans including entry and exit costs from per-asset bar log allocation.
    removed_log=np.zeros(len(inds))
    for (eid,b),value in episode_logs.items():
        if eid in removed_set:removed_log[b]+=value
    alt=np.exp(np.cumsum(logs.sum(axis=1)-removed_log))*capital
    stats['no_top3_mdd']=float(np.max(1-alt/np.maximum.accumulate(np.r_[capital,alt])[1:]))
    altday=np.exp(np.cumsum(nb))*capital;stats['no_best_day_mdd']=float(np.max(1-altday/np.maximum.accumulate(np.r_[capital,altday])[1:]))
    total_log=float(logs.sum());expected=math.log(max(stats['final_nav'],1e-300)/capital)
    stats['log_reconciliation_error']=abs(total_log-expected)
    if stats['reliable'] and stats['log_reconciliation_error']>1e-8:raise AssertionError('Account log attribution mismatch')
    folds=[];prior=capital
    for year,part in daily.groupby(daily.index.year):
        f=summary(part,prior);f.update(year=int(year),fee_usd=float(part.fee.sum()),slippage_usd=float(part.slippage.sum()),funding_debit_usd=float(part.funding_debit.sum()),funding_credit_usd=float(part.funding_credit.sum()),turnover=float(part.turnover.sum()/(len(part)/365.25)),end_residual_usd=float(part.residual_usd.iloc[-1]));folds.append(f);prior=float(part.nav.iloc[-1])
    stats['profitable_folds']=sum(f['cagr']>0 for f in folds);stats['worst_fold']=min(f['cagr'] for f in folds)
    return dict(metrics=stats,daily=daily,folds=folds,episodes=episodes,orders=orders,fills=fills,bars=bars if details else None,quantities=np.array(qrows) if details else None,asset_log=logs if details else None,episode_logs=[dict(episode=e,bar=b,log_growth=v) for (e,b),v in episode_logs.items()] if details else None,assets=names)
