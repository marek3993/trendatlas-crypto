"""Continuous causal book and calendar metrics for every rule and benchmark."""
from __future__ import annotations
import math
import numpy as np
import pandas as pd
from .contract import load, validate_folds
from .market import targets, validate_genes, digest

def curve_metrics(dates, equity, initial=100.):
    dates=pd.DatetimeIndex(dates)
    equity=np.asarray(equity,dtype=float)
    if len(equity)!=len(dates) or not len(equity) or not np.isfinite(equity).all() or (equity<=0).any():
        raise ValueError('invalid_equity_curve')
    if len(dates)>1 and not np.all(np.diff(dates.values)==np.timedelta64(1,'D')):
        raise ValueError('calendar_gap_not_allowed')
    years=((dates[-1]+pd.Timedelta(days=1))-dates[0]).days/365.25
    nav=np.r_[initial,equity]
    log=np.log(nav[1:]/nav[:-1]); returns=np.expm1(log)
    growth=float(np.log(equity[-1]/initial))
    cagr=math.expm1(growth/years)
    mdd=float(np.max(1-nav/np.maximum.accumulate(nav)))
    std=float(np.std(returns,ddof=1)) if len(returns)>1 else 0.
    sharpe=float(np.mean(returns)/std*math.sqrt(365.25)) if std>1e-12 else None
    return dict(cagr=cagr,mdd=mdd,sharpe=sharpe,calmar=cagr/mdd if mdd>1e-12 else None,
        net_return=float(equity[-1]/initial-1),elapsed_calendar_days=round(years*365.25),
        start=dates[0].strftime('%Y-%m-%d'),end=dates[-1].strftime('%Y-%m-%d'),
        log_growth=growth,no_best_day_cagr=math.expm1((growth-max(0.,float(log.max())))/years))

def benchmark_target(m, name, i):
    w=np.zeros(len(m.assets));j=m.assets.index('BTCUSDT')
    if name=='CASH':return w
    if name=='BTC_BUY_HOLD':w[j]=1.
    elif name=='BTC_SMA200':w[j]=float(m.close[i,j]>m.features['sma200'][i,j])
    elif name=='BTC_SMA100':w[j]=float(m.close[i,j]>m.features['sma100'][i,j])
    elif name=='BTC_HALF':w[j]=.5
    else:raise ValueError('unknown_benchmark')
    return w

def evaluate(m, strategy, folds, *, cost_mult=1., delay_entries=False, production_targets=None,
             selected_by_fold=None, initial_state=None):
    """One book across contiguous folds. Fixed-rule trials are never called nested selection."""
    c=load(); validate_folds(folds,c)
    lo=m.dates.get_indexer([pd.Timestamp(folds[0][0])])[0]
    hi=m.dates.get_indexer([pd.Timestamp(folds[-1][1])])[0]
    if lo<200 or hi<lo:raise ValueError('insufficient_market_warmup')
    if isinstance(strategy,dict):validate_genes(strategy)
    n=len(m.assets);s=initial_state or {}
    cash=float(s.get('cash',100.));q=np.array(s.get('quantity',np.zeros(n)),dtype=float)
    previous_mark=np.array(s.get('previous_mark',np.where(np.isfinite(m.close[lo-1]),m.close[lo-1],0)),dtype=float)
    initial=cash+float(q@previous_mark);nav_before=initial
    state=s.get('strategy_state',{'cooldown':{},'previous':None})
    state['cooldown']={int(k):v for k,v in state.get('cooldown',{}).items()}
    episodes=s.get('episodes',[None]*n);closed=[];daily=[];asset_log=np.zeros(n)
    fee=c['execution']['fee_bps']/10000*cost_mult;slip=c['execution']['slippage_bps']/10000*cost_mult
    borrow=c['execution']['borrow_apr']*cost_mult/365.25
    costs=turnover=0.; trades=0;pending=None;last_target=s.get('last_signal')
    current_rule=s.get('current_rule');fold_of={a:k for k,(a,b) in enumerate(folds)}
    rule=strategy;fold_index=0
    for i in range(lo,hi+1):
        day=m.dates[i].strftime('%Y-%m-%d')
        if day in fold_of:
            fold_index=fold_of[day]
            rule=selected_by_fold[fold_index] if selected_by_fold is not None else strategy
        rule_key=digest(rule)
        if rule_key!=current_rule:
            state={'cooldown':{},'previous':None};last_target=None;pending=None;current_rule=rule_key
        if isinstance(rule,dict):
            desired_weights=targets(m,rule,i-1,state)
            state['previous']=desired_weights.copy()
        elif rule=='PRODUCTION':
            prior=m.dates[i-1].strftime('%Y-%m-%d')
            if production_targets is None or prior not in production_targets:raise ValueError('missing_canonical_production_target:'+prior)
            asset,exposure=production_targets[prior];desired_weights=np.zeros(n)
            if exposure:
                symbol=asset+'USDT'
                if symbol not in m.assets:raise ValueError('missing_production_asset:'+symbol)
                desired_weights[m.assets.index(symbol)]=exposure
        else:desired_weights=benchmark_target(m,rule,i-1)
        if not np.isfinite(desired_weights).all() or (desired_weights<0).any() or desired_weights.sum()>c['execution']['maximum_gross']+1e-9:
            raise ValueError('invalid_or_excess_target')
        signal=desired_weights.copy()
        if delay_entries:
            # Increases execute one open later; intervening lower target cancels stale demand.
            released=np.zeros(n) if last_target is None else np.array(last_target,dtype=float)
            desired_weights=np.minimum(desired_weights,released)
        last_target=signal.tolist()
        op=m.opening[i];cl=m.close[i];low=m.low[i]
        held=q>1e-12
        missing=held & (~np.isfinite(op)|~np.isfinite(cl)|(op<=0)|(cl<=0))
        if np.any(missing):raise ValueError('missing_held_asset_price:'+day+':'+','.join(m.assets[j] for j in np.flatnonzero(missing)))
        safe_op=np.where(np.isfinite(op)&(op>0),op,0.)
        safe_cl=np.where(np.isfinite(cl)&(cl>0),cl,safe_op)
        if np.any((desired_weights>0)&(safe_op<=0)):raise ValueError('missing_entry_price')
        equity_open=cash+float(q@safe_op)
        if equity_open<=0:raise ValueError('insolvent_book')
        pnl=q*(safe_op-previous_mark)
        gross=float(desired_weights.sum())
        # Explicitly fund costs; do not silently clip benchmark/model exposures to 95%.
        pre_trade_notional=q*safe_op
        desired_notional=desired_weights*equity_open
        for _ in range(8):
            delta=desired_notional-pre_trade_notional
            estimate=float(np.sum(np.abs(delta)*(slip+fee+np.where(delta>0,1,-1)*fee*slip)))
            desired_notional=desired_weights*(equity_open-estimate)
        desired=np.divide(desired_notional,safe_op,out=np.zeros(n),where=safe_op>0)
        charge_by_asset=np.zeros(n)
        for sign in (-1,1):
            indices=np.flatnonzero((desired-q)*sign>1e-10)
            for j in indices:
                delta=abs(desired[j]-q[j]);price=safe_op[j]*(1+sign*slip);charge=delta*price*fee
                cash-=sign*delta*price+charge;q[j]+=sign*delta
                debit=delta*safe_op[j]*slip+charge
                pnl[j]-=debit;costs+=debit;charge_by_asset[j]+=debit
                turnover+=delta*safe_op[j]/nav_before;trades+=1
                if abs(q[j])<1e-10:q[j]=0.
                if episodes[j] is None and sign>0:
                    episodes[j]={'id':digest([m.assets[j],day,trades])[:24],'asset':m.assets[j],
                        'start':day,'end':None,'status':'OPEN','log_contribution':0.,'pnl_usd':0.,
                        'entry':price,'high_water':price,'days':[]}
        if isinstance(rule,dict) and rule['family']=='N':
            atr=m.features['atr'+str(rule['atr_days'])][i-1]
            for j in np.flatnonzero(q>1e-12):
                ep=episodes[j]
                if not np.isfinite(atr[j]):raise ValueError('missing_stop_atr')
                stop=max(ep['entry']-rule['initial_stop_atr']*atr[j],ep['high_water']-rule['trailing_stop_atr']*atr[j])
                if np.isfinite(low[j]) and low[j]<=stop:
                    reference=min(safe_op[j],stop);price=reference*(1-slip);delta=q[j];charge=delta*price*fee
                    cash+=delta*price-charge;q[j]=0.
                    debit=delta*(reference-price)+charge;pnl[j]+=delta*(reference-safe_op[j])-debit
                    costs+=debit;charge_by_asset[j]+=debit;turnover+=delta*reference/nav_before;trades+=1
                    state['cooldown'][int(j)]=int(i+7)
                else:ep['high_water']=max(ep['high_water'],float(m.high[i,j]))
        financing=max(0.,-cash)*borrow
        if financing:
            alloc=q*safe_op;alloc/=alloc.sum()
            pnl-=alloc*financing;cash-=financing;costs+=financing;charge_by_asset+=alloc*financing
        pnl+=q*(safe_cl-safe_op)
        equity=cash+float(q@safe_cl)
        if equity<=0 or not math.isfinite(equity):raise ValueError('invalid_equity')
        if not math.isclose(equity-nav_before,float(pnl.sum()),rel_tol=1e-8,abs_tol=1e-8):raise AssertionError('pnl_reconciliation')
        daily_log=math.log(equity/nav_before)
        factor=daily_log/(equity-nav_before) if abs(equity-nav_before)>1e-12 else 1/nav_before
        contribution=pnl*factor;asset_log+=contribution
        for j in np.flatnonzero(np.abs(contribution)>0):
            ep=episodes[j]
            if ep is None:raise AssertionError('unassigned_episode')
            ep['log_contribution']+=float(contribution[j]);ep['pnl_usd']+=float(pnl[j])
            ep['days'].append({'date':day,'log_contribution':float(contribution[j]),'pnl_usd':float(pnl[j])})
        for j,ep in enumerate(episodes):
            if ep is not None and q[j]==0:
                ep['end']=day;ep['status']='CLOSED';closed.append(ep);episodes[j]=None
        daily.append({'date':day,'equity':equity,'log_return':daily_log,'cash':cash,
            'gross_exposure':float(q@safe_cl)/equity,'costs_usd':float(charge_by_asset.sum()),
            'fold':fold_index,'rule':rule_key})
        nav_before=equity;previous_mark=safe_cl.copy()
    metrics=curve_metrics([r['date'] for r in daily],[r['equity'] for r in daily],initial)
    years=metrics['elapsed_calendar_days']/365.25;growth=metrics['log_growth']
    if not math.isclose(float(asset_log.sum()),growth,rel_tol=1e-8,abs_tol=1e-8):raise AssertionError('log_attribution')
    all_episodes=closed+[ep for ep in episodes if ep is not None]
    # Contributions from carry-in episodes before this segment remain in checkpoint, not segment metric.
    segment_episodes=[]
    for ep in all_episodes:
        contribution=sum(d['log_contribution'] for d in ep['days'] if d['date']>=folds[0][0])
        segment_episodes.append({**ep,'segment_log_contribution':contribution})
    positive_closed=sorted((ep for ep in segment_episodes if ep['status']=='CLOSED' and ep['segment_log_contribution']>0),key=lambda ep:ep['segment_log_contribution'],reverse=True)
    dominant_asset=int(np.argmax(asset_log))
    dominant_episode=max(segment_episodes,key=lambda ep:ep['segment_log_contribution']) if segment_episodes else None
    metrics.update(turnover=turnover/years,cost_drag=costs/initial/years,costs_usd=costs,trades=trades,
        closed_episodes=len(closed),open_episodes=sum(ep is not None for ep in episodes),
        asset_concentration=float(asset_log[dominant_asset])/growth if growth>0 and asset_log[dominant_asset]>0 else None,
        trade_concentration=dominant_episode['segment_log_contribution']/growth if growth>0 and dominant_episode and dominant_episode['segment_log_contribution']>0 else None,
        dominant_asset=m.assets[dominant_asset] if asset_log[dominant_asset]>0 else None,
        dominant_asset_log_contribution=float(asset_log[dominant_asset]),dominant_episode=dominant_episode['id'] if dominant_episode else None,
        dominant_episode_log_contribution=dominant_episode['segment_log_contribution'] if dominant_episode else None,
        no_top3_trades_cagr=math.expm1((growth-sum(ep['segment_log_contribution'] for ep in positive_closed[:3]))/years) if len(positive_closed)>=3 else None,
        top3_removed=[ep['id'] for ep in positive_closed[:3]],top3_status='COMPLETE' if len(positive_closed)>=3 else 'INCONCLUSIVE_FEWER_THAN_3_POSITIVE_CLOSED_EPISODES')
    # Fold metrics refer to the SAME book; initial fold NAV is prior day's real NAV.
    fold_results=[];before=initial
    for k,(a,b) in enumerate(folds):
        rows=[r for r in daily if r['fold']==k]
        fm=curve_metrics([r['date'] for r in rows],[r['equity'] for r in rows],before)
        fm['cost_drag']=sum(r['costs_usd'] for r in rows)/before/(len(rows)/365.25)
        fold_results.append({'start':a,'end':b,'metrics':fm});before=rows[-1]['equity']
    worst=min(fold_results,key=lambda f:f['metrics']['net_return'])
    metrics.update(profitable_fold_fraction=sum(f['metrics']['net_return']>0 for f in fold_results)/len(fold_results),
        worst_fold_return=worst['metrics']['net_return'],worst_fold=[worst['start'],worst['end']])
    state={k:(v.tolist() if isinstance(v,np.ndarray) else v) for k,v in state.items()}
    return dict(metrics=metrics,folds=fold_results,equity=daily,
        assets=[{'asset':a,'log_contribution':float(v)} for a,v in zip(m.assets,asset_log)],episodes=all_episodes,
        checkpoint=dict(cash=cash,quantity=q.tolist(),previous_mark=previous_mark.tolist(),episodes=episodes,
            strategy_state=state,last_signal=last_target,current_rule=current_rule,end=metrics['end']),
        audit={'pnl_reconciled':True,'log_attribution_reconciled':True,'continuous_book':True,
            'timing':'prior_close_next_open','outer_read':False,'forward_read':False,
            'selection_type':'chronological_nested' if selected_by_fold is not None else 'fixed_rule_retrospective_development'})

def suite(m,strategy,folds,**kwargs):
    nominal=evaluate(m,strategy,folds,**kwargs)
    double=evaluate(m,strategy,folds,cost_mult=2,**kwargs)
    delayed=evaluate(m,strategy,folds,delay_entries=True,**kwargs)
    nominal['metrics'].update(double_cost_cagr=double['metrics']['cagr'],delayed_entry_cagr=delayed['metrics']['cagr'])
    nominal['stresses']={'double_cost':double['metrics'],'delayed_entry':delayed['metrics']}
    return nominal

def eligibility(metrics):
    f=load()['development_filters'];reasons=[]
    if metrics['mdd']>f['mdd_max']:reasons.append('mdd_cap')
    for key in ('asset_concentration','trade_concentration'):
        if metrics[key] is None:reasons.append(key+'_undefined')
    for key in ('double_cost_cagr','delayed_entry_cagr','no_best_day_cagr','no_top3_trades_cagr'):
        if metrics.get(key) is None or metrics[key]<=0:reasons.append(key+'_not_positive_or_inconclusive')
    if metrics['profitable_fold_fraction']<f['profitable_fold_fraction_min']:reasons.append('profitable_fold_fraction')
    return not reasons,reasons
