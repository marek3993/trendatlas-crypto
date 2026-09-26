"""Source archaeology: source functions for rules, common ledger for every payoff."""
from pathlib import Path
from types import FunctionType
from dataclasses import asdict
import contextlib, io, json, sys
import numpy as np
import pandas as pd
import engine as e

HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1]
for p in [ROOT,ROOT/'src',ROOT/'scripts']:sys.path.insert(0,str(p))
import phase60_selective_restore_robustness as p60
import phase62_btc_overlay as p62
import phase63_btc_participation_overlay as p63
import phase66e_probation_governance as gov
import phase66g_production_candidate_live as p66
import phase67j_final_narrow_validation_pack as p67
import phase68g_portfolio_exposure_leverage_validation as lev
import phase68h_dynamic_leverage_ladder_candidate as ladder
import phase68j_tail_risk_guardrail_check as tail
import dev_only_phase68g_etf_flow_impulse_probe as etf
import dev_only_phase68g_etf_flow_impulse_cooldown_sensitivity as cool
import dev_only_production_core_btc_candidate_persistence_early_risk_compare as persist

def source_core(m,kind='original'):
    # One inert trailing OHLC row makes source's signal D visible, without
    # consuming ret_next/best_available_next diagnostics or a future price.
    raw={}
    for a in e.spec()['universe']['assets'][:12]:
        f=m['raw'][a].copy();sentinel=f.iloc[[-1]].copy();sentinel.index=[f.index[-1]+pd.Timedelta(days=1)]
        raw[a+'USDT']=pd.concat([f,sentinel])
    with contextlib.redirect_stdout(io.StringIO()):tables=p60.build_daily_tables(raw,m['macro'],p60.ALL_SYMBOLS)
    for symbol,f in tables.items():
        f.index=pd.DatetimeIndex(f.signal_ts);f.drop(columns=['ret_next_1d','best_available_next','signal_ts'],inplace=True)
        a=symbol[:-4];eligible=pd.Series(m['eligible'][:,m['assets'].index(a)],index=m['dates'])
        tables[symbol]=f.loc[eligible.reindex(f.index).fillna(False)]
    # Repair source fillna(0).rank(): unlisted/not-admitted columns must not
    # participate in the denominator or in another asset's historical rank.
    known=pd.concat({a:f.close for a,f in tables.items()},axis=1).sort_index()
    cross=pit_cross_sections(known)
    for a,f in tables.items():
        for col,values in cross.items():f[col]=values[a].reindex(f.index).fillna(0.)
    selected=p60.select_daily_top1_variant(tables,p60.PINNED_PHASE60_DEPENDENCY_MODEL_KEY).selected.str.replace('USDT','',regex=False)
    if kind=='vol_adjusted':return phase2(m,'vol_adjusted',size=False,schedule='daily',pool=e.spec()['universe']['assets'][:12]),tables
    if kind=='slow':selected=slow_core(selected,tables)
    return e.admit(m,e.target(m,selected.reindex(m['dates']).fillna('CASH'))),tables

def slow_core(selected,tables):
    held='CASH';entry=None;chosen=[]
    for date,a in selected.items():
        current=tables.get(held+'USDT')
        # Preserve the original selector's market-wide CASH gate, as well as
        # the held name's candidate gate. Only permitted rotations are slowed.
        valid=a!='CASH' and current is not None and date in current.index and p60.candidate_ok(current.loc[date])
        if not valid:held='CASH'
        if date.is_month_end:
            can_switch=True
            if held!='CASH' and a!='CASH':
                age=(date-entry).days if entry is not None else 999
                old=p60.candidate_score(tables[held+'USDT'].loc[date]);new=p60.candidate_score(tables[a+'USDT'].loc[date])
                can_switch=age>=30 and new>=old+10
            if can_switch and a!=held:held=a;entry=date
        chosen.append(held)
    return pd.Series(chosen,index=selected.index)

def pit_cross_sections(known):
    ready=known.notna();r20=known.pct_change(20,fill_method=None);r90=known.pct_change(90,fill_method=None)
    x20=(r20.sub(r20.BTCUSDT,axis=0).fillna(0.).where(ready).rank(axis=1,pct=True)-.5)*200
    x90=(r90.sub(r90.BTCUSDT,axis=0).fillna(0.).where(ready).rank(axis=1,pct=True)-.5)*200
    r5=known.pct_change(5,fill_method=None)
    return dict(xs20=x20,xs90=x90,xs_persist=(.6*x20+.4*x90).rolling(5).mean(),xs_accel=x20-x90,thrust_ret5=(r5.where(ready).rank(axis=1,pct=True)-.5)*200)

def eligible_rank_scores(values,eligible):
    ok=eligible&np.isfinite(values);out=np.full(len(values),np.nan);n=int(ok.sum())
    if n:out[ok]=(pd.Series(np.asarray(values)[ok]).rank(method='first').to_numpy()-1)/n
    return out

def phase2(m,family,*,size=True,schedule='monthly',pool=None):
    dates=m['dates'];c=pd.DataFrame(m['prices'][:,:,3],index=dates,columns=m['assets']);rets=c.pct_change(fill_method=None)
    pool_mask=np.array([pool is None or a in pool for a in m['assets']],dtype=bool)
    mom={n:c/c.shift(n)-1 for n in [30,90,180]};vol20=rets.rolling(20).std()*np.sqrt(365.25);vol60=rets.rolling(60).std()*np.sqrt(365.25)
    sma=c.rolling(200).mean();high=c.shift(1).rolling(55).max();low=c.shift(1).rolling(20).min();breakout=np.zeros(c.shape,bool)
    for j in range(1,len(c)):breakout[j]=(breakout[j-1]|(c.iloc[j].to_numpy()>high.iloc[j].to_numpy()))&(c.iloc[j].to_numpy()>=low.iloc[j].to_numpy())
    held='CASH';entry=0;rows=[]
    for j,d in enumerate(dates):
        eligible=m['eligible'][j]&pool_mask&np.isfinite(vol60.iloc[j].to_numpy());score=mom[90].iloc[j].to_numpy().copy();ok=eligible&np.isfinite(score)
        if family in ['vol_adjusted','slow_hysteresis']:ok &= score>0
        if family=='vol_adjusted':score=score/np.maximum(.1,vol60.iloc[j].to_numpy())
        if family=='ensemble':
            votes=sum((mom[n].iloc[j].to_numpy()>0).astype(int) for n in mom)+(c.iloc[j].to_numpy()>sma.iloc[j].to_numpy()).astype(int)
            ranks=[eligible_rank_scores(mom[n].iloc[j].to_numpy(),eligible) for n in mom]
            score=np.mean(ranks,axis=0)+.1*breakout[j];ok &= votes>=3
        btc=m['assets'].index('BTC')
        if family=='regime_allocation':
            btc_ok=eligible[btc] and c.iloc[j,btc]>sma.iloc[j,btc]
            if not btc_ok:held='CASH'
            alt=np.where(ok&(np.arange(len(score))!=btc),score,-np.inf);best=int(np.argmax(alt))
            breadth=np.mean((c.iloc[j].to_numpy()>sma.iloc[j].to_numpy())[eligible]) if eligible.any() else 0.
            proposed=m['assets'][best] if breadth>=.6 and alt[best]>score[btc]+.10 else 'BTC'
            if not btc_ok:proposed='CASH'
        else:
            a=int(np.argmax(np.where(ok,score,-np.inf)));proposed=m['assets'][a] if ok[a] else 'CASH'
        if held!='CASH' and not ok[m['assets'].index(held)]:held='CASH'
        # Source controller resets at each execution-year boundary. On the
        # signal calendar that is Dec 30 for the common Jan 1 D+2 fill.
        first=(j==0 or (d+pd.Timedelta(days=2)).year!=(dates[j-1]+pd.Timedelta(days=2)).year)
        if first:held='CASH';entry=j
        if first or schedule=='daily' or d.is_month_end:
            keep=False
            if family=='slow_hysteresis' and held!='CASH' and proposed!='CASH':
                keep=j-entry<30 or score[m['assets'].index(proposed)]<score[m['assets'].index(held)]+.10
            if not keep and proposed!=held:held=proposed;entry=j
        w=0.
        if held!='CASH':
            a=m['assets'].index(held);w=1.
            if size:
                w=min(1.25,.4/max(.1,float(vol20.iloc[j,a])));ratio=vol20.iloc[j,a]/max(.01,float(vol60.iloc[j,a]))
                if c.iloc[j,btc]<=sma.iloc[j,btc] or ratio>1.8:w=min(w,.5)
                elif ratio>1.3:w=min(w,.75)
                elif ratio>1.2:w=min(w,1.)
        rows.append((held,w))
    return e.admit(m,pd.DataFrame(rows,index=dates,columns=['asset','weight']))

def add_shadow(m,t,mult=1.):
    x=e.admit(m,t);r=e.simulate(m,x,start=e.spec()['history_start'],mult=mult,terminal_exit=False)
    x['strategy_return']=r['daily'].net_return.reindex(x.index).fillna(0.);x['equity']=(1+x.strategy_return).cumprod()
    if 'signal_regime' not in x:x['signal_regime']=np.where(x.asset.eq('CASH'),'CASH','BASE')
    x['executed_regime']=x.signal_regime.shift(2).fillna('CASH');x['executed_position']=x.asset.shift(2).fillna('CASH')
    return x

def participation(m,base,phase=63,mult=1.):
    x=add_shadow(m,base,mult);x['base_return']=x.strategy_return;x['base_selected_symbol']=x.asset
    x['btc_close']=m['raw']['BTC'].close.reindex(x.index);x['btc_return']=x.btc_close.pct_change(fill_method=None).fillna(0.)
    for n in [10,20,30]:x[f'base_rolling_ret_{n}']=(1+x.base_return).rolling(n).apply(np.prod,raw=True)-1
    if phase==63:
        cfg=p63.parse_variant_key(gov.CURRENT_WINNER_KEY);x=p63.compute_regime_columns(x,cfg);flag=x.btc_preference
    else:
        cfg=next(z for z in p62.build_variant_grid() if z.name=='phase62_btcov_default');x=p62.compute_regime_columns(x,cfg);flag=x.btc_led
    x['signal_regime']=np.where(x.risk_off.fillna(True),'CASH',np.where(flag.fillna(False),'BTC','BASE'))
    x['asset']=np.where(x.signal_regime.eq('BTC'),'BTC',np.where(x.signal_regime.eq('CASH'),'CASH',base.asset))
    x['weight']=x.asset.ne('CASH').astype(float)
    if phase==63:
        x['baseline_is_weak']=x.base_strength_lb<=gov.OverlayConfig().weak_base_threshold
        x['trend_score']=p66.build_trend_barometer_history(x,gov.OverlayConfig()).trend_score.fillna(-1.)
    return add_shadow(m,x,mult)

def slice_metrics(returns):
    r=pd.to_numeric(returns).to_numpy(float);eq=np.r_[1.,np.cumprod(1+r)]
    return (eq[-1]-1)*100,float((eq/np.maximum.accumulate(eq)-1).min()*100)

def governance(m,base,*,reference=False,pruned=True,ssot=False,mult=1.):
    module=p67 if reference else gov
    if reference:
        overlay,cfg,_=p67.build_profiles()[0];pool=e.spec()['universe']['ssot_shortlist'] if ssot else e.spec()['universe']['runtime_shortlist']
        pool=[a for a in pool if not (pruned and a=='NEO')]
    else:
        overlay=gov.OverlayConfig();cfg=p66.build_winner_config(260)
        pool=[a for a in e.spec()['universe']['assets'][:12] if a!='BTC' and not (pruned and a in ['LTC','SOL'])]
    shadows={}
    for a in pool:
        x=base.copy();x['candidate_close']=m['raw'][a].close.reindex(x.index)
        x['candidate_return']=x.candidate_close.pct_change(fill_method=None).fillna(0.)
        x=(p67.compute_candidate_signal(x,overlay) if reference else gov.compute_asset_signal(x,overlay))
        flag=x.candidate_signal & m['eligible'][:,m['assets'].index(a)]
        x['asset']=np.where(flag,a,base.asset);x['weight']=np.where(flag,1.,base.weight)
        x['signal_regime']=np.where(flag,'CANDIDATE',base.signal_regime)
        x=add_shadow(m,x,mult);x['candidate_execute']=flag.shift(2,fill_value=False);shadows[a]=x
    # Use original governance state machine, privately replacing only metric,
    # eligibility and terminal-dependent scheduler defects. It never writes.
    anchor=pd.Timestamp('2019-05-05')
    schedule=pd.date_range(anchor,m['dates'][-1],freq='7D')
    def reviews(index,train_days,step_days):return list(schedule)
    # Cache arrays, retaining the source evaluator's exact arithmetic. This
    # avoids repeated pandas label slicing in thousands of weekly reviews.
    base_values=base.strategy_return.to_numpy(float)
    values={a:x.strategy_return.to_numpy(float) for a,x in shadows.items()}
    triggers={a:x.candidate_execute.to_numpy(int) for a,x in shadows.items()}
    locs={d:i for i,d in enumerate(base.index)}
    def window(v,i,n):
        eq=np.r_[1.,np.cumprod(1+v[max(0,i-n+1):i+1])]
        return (eq[-1]-1)*100,float((eq/np.maximum.accumulate(eq)-1).min()*100)
    def evaluate(a,date,baseline,strategies,gcfg):
        i=locs[date];bt,bd=window(base_values,i,gcfg.trailing_train_days);br,_=window(base_values,i,gcfg.recent_days)
        ct,cd=window(values[a],i,gcfg.trailing_train_days);cr,_=window(values[a],i,gcfg.recent_days)
        dd=max(0.,bd-cd)
        meta=dict(asset=a,train_total_delta_pct=ct-bt,recent_total_delta_pct=cr-br,train_dd_worsen_pct=dd,train_triggers=int(triggers[a][max(0,i-gcfg.trailing_train_days+1):i+1].sum()))
        passed=meta['train_triggers']>=gcfg.min_triggers_in_train and meta['train_total_delta_pct']>=gcfg.min_total_delta_pct and meta['recent_total_delta_pct']>=gcfg.min_recent_delta_pct and dd<=gcfg.max_allowed_dd_worsen_pct
        score=meta['recent_total_delta_pct']*4+meta['train_total_delta_pct']*1.5-dd*1.25+meta['train_triggers']*.15
        if reference:
            _,base_down=window(base_values,i,gcfg.downside_lookback_days);_,cand_down=window(values[a],i,gcfg.downside_lookback_days)
            down=max(0.,base_down-cand_down);meta['downside_dd_worsen_pct']=down
            passed=passed and down<=gcfg.downside_max_worsen_pct and meta['recent_total_delta_pct']>=gcfg.promotion_margin_pct;score-=1.5*down
        passed=passed and bool(m['eligible'][m['dates'].get_loc(date),m['assets'].index(a)])
        meta.update(passed_filters=passed,score=score if passed else -1e18);return meta
    fn=p67.simulate_weekly_challenger_governance if reference else gov.simulate_governance_strategy_probation
    glob=dict(fn.__globals__);glob.update(evaluate_asset_for_date=evaluate,build_rebalance_dates=reviews,slice_metrics_from_returns=slice_metrics)
    run=FunctionType(fn.__code__,glob)
    def extended(x):
        last=x.iloc[[-1]].copy();last.index=[x.index[-1]+pd.Timedelta(days=1)];return pd.concat([x,last])
    _,decisions,leaders=run(extended(base),{a:extended(x) for a,x in shadows.items()},cfg)
    out=base.copy();out['chosen_asset']=''
    for row in decisions.itertuples():
        date=pd.Timestamp(row.decision_date);period=(out.index>=date)&(out.index<date+pd.Timedelta(days=6))
        out.loc[period,'chosen_asset']=row.selected_asset
        if row.selected_asset:
            cols=['asset','weight','signal_regime'];out.loc[period,cols]=shadows[row.selected_asset].loc[period,cols].to_numpy()
    return add_shadow(m,out,mult),decisions,dict(overlay=asdict(overlay),governance=asdict(cfg),pool=pool)

def routed(m,core,ref):
    x=core.copy();policy=ref.signal_regime.where(ref.signal_regime.isin(['BASE','BTC','CASH']),ref.asset)
    policy=core.chosen_asset.where(core.chosen_asset.ne(''),policy)
    # BASE means the underlying explicitly reconstructed phase66 target. A named
    # chosen override means THAT asset, never the core's synthetic return.
    x['asset']=policy.where(policy.ne('BASE'),core.asset);x['weight']=x.asset.ne('CASH').astype(float);x['policy']=policy
    return e.admit(m,x)

def wrap(m,raw,*,leverage=1.25,dynamic=False,mult=1.):
    x=add_shadow(m,raw,mult);policy=x.get('policy',x.asset);trend=x.trend_score.fillna(-1.)
    port=pd.DataFrame(dict(date=x.index,base_ret=x.strategy_return.to_numpy(),portfolio_held_asset=policy.to_numpy(),is_exposed=policy.ne('CASH').to_numpy()))
    tr=pd.DataFrame(dict(date=x.index,trend_score=trend.to_numpy()))
    if dynamic:
        w=ladder.build_validation_wrapper(port,tr,pd.DataFrame(),ladder.ValidationVariant('replay','dynamic',0),.12,10,.10,20,-.08,-.04,.5,1.25,1.5,'taker',4.5,1.5,0.,0.)
    else:w=lev.build_validation_wrapper(port,tr,pd.DataFrame(),lev.ValidationVariant('replay',leverage),.12,10,.10,20,-.08,-.04)
    permitted=w.trend_gate_pass.to_numpy()&~w.stress_block_day.to_numpy()
    out=x.copy();out['weight']=np.where(permitted&w.is_exposed.to_numpy()&x.asset.ne('CASH').to_numpy(),w.effective_leverage.to_numpy(),0.)
    out['asset']=out.asset.where(out.weight.gt(0),'CASH');out['candidate_asset']=policy
    out['trend_permission_active']=permitted;out['stress_block_day']=w.stress_block_day.to_numpy();out['hard_invalidation']=False
    out['baseline_non_cash']=out.weight.gt(0);out['baseline_cash']=~out.baseline_non_cash
    return e.admit(m,out)

def persistence(m,x):
    out=x.copy();out['btc_candidate_persistence_rows']=persist.compute_btc_candidate_persistence_rows(out)
    states=pd.Series(persist.build_override_states(out,variant_id='btc_candidate_persistence_10d_075'),index=out.index)
    active=states.eq('EARLY_RISK');out.loc[active,['asset','weight']]=['BTC',.75];out['persistence_active']=active
    return e.admit(m,out)

def etf_overlay(m,x,days=15,availability_delay=0):
    panel=m['etf'].copy()
    for col in ['date','us_trading_session_date','causal_available_for_btc_utc_day']:panel[col]=pd.to_datetime(panel[col])
    assert panel.date.eq(panel.causal_available_for_btc_utc_day).all()
    assert panel.date.gt(panel.us_trading_session_date).all(), 'same-day ETF publication rejected'
    for col in ['flow_2_of_last_3_positive_flag','probe_input_ready_flag','dev_only','non_authoritative','official_truth','strategy_advancement']:panel[col]=etf.to_bool_series(panel[col])
    for col in ['date','causal_available_for_btc_utc_day']:panel[col]+=pd.Timedelta(days=availability_delay)
    panel=panel.set_index('date');out=x.copy();btc=m['raw']['BTC'].close.reindex(out.index)
    btc_frame=pd.DataFrame(dict(btc_close=btc,btc_return=btc.pct_change(fill_method=None).fillna(0.),btc_ema10=btc.ewm(span=10,adjust=False).mean()))
    btc_frame['btc_price_filter_pass']=btc_frame.btc_close>btc_frame.btc_ema10
    baseline=pd.DataFrame(dict(cash_day=out.weight.eq(0),stress_block_active=out.stress_block_day,portfolio_held_asset=out.asset,effective_leverage=out.weight,realistic_ret_gross=0.),index=out.index)
    if panel.index.intersection(out.index).empty:out['etf_active']=False;out['cooldown_active']=False;return out
    full=etf.build_full_history_frame(baseline,panel,btc_frame);states,_=cool.build_cooldown_state_machine(full,days)
    active=states.early_risk_active;out.loc[active,['asset','weight']]=['BTC',.5];out['etf_active']=active;out['cooldown_active']=states.cooldown_active
    return e.admit(m,out)

def build(m,*,mult=1.,include_sensitivities=True,progress=True):
    result={};meta={}
    def log(x):
        if progress:print(x,flush=True)
    def chain(kind='original',prefix=''):
        log('Reconstructing '+kind+' selector and nested shadow portfolios')
        base,_=source_core(m,kind);part=participation(m,base,mult=mult)
        core,dec,cm=governance(m,part,pruned=True,mult=mult);ref,rd,rm=governance(m,core,reference=True,pruned=True,mult=mult)
        route=routed(m,core,ref);static=wrap(m,route,mult=mult);durable=persistence(m,static);current=etf_overlay(m,durable)
        meta[kind]=dict(core=cm,reference=rm,core_reviews=len(dec),reference_reviews=len(rd))
        return base,part,core,ref,route,static,durable,current
    base,part,core,ref,route,static,durable,current=chain()
    result['phase61_core_rotation']=base;result['phase62_btc_overlay_default']=participation(m,base,62,mult)
    result['phase63_btc_participation']=part;result['phase66g_production_soft_filters']=core;result['phase67j_no_neo_main']=ref
    result['phase68g_66g_1p25x_candidate']=static;result['phase68g_66g_1p50x_candidate']=wrap(m,route,leverage=1.5,mult=mult)
    result['phase68g_btc_persistence_10d_early_risk_075']=durable;result['phase68g_etf_flow_impulse_early_risk_cooldown_15']=current
    result['phase68h_dynamic_leverage_ladder']=wrap(m,route,dynamic=True,mult=mult)
    for parent in ['phase68g_66g_1p25x_candidate','phase68g_66g_1p50x_candidate','phase68h_dynamic_leverage_ladder']:
        parent_shadow=add_shadow(m,result[parent],mult)
        f=pd.DataFrame({'parent_realistic_ret':parent_shadow.strategy_return.to_numpy()})
        for name,fn in [('g1_adverse_cd2',tail.apply_g1_adverse_cooldown),('g2_dd5_cd3',tail.apply_g2_dd5_brake)]:
            # Original output is next-day action; relabel it to the close that
            # actually knew the trigger, then apply the common D+2 fill once.
            padded=pd.concat([f,pd.DataFrame({'parent_realistic_ret':[0.]})],ignore_index=True)
            guard=fn(padded).guardrail_forced_1p00.iloc[1:].to_numpy();t=result[parent].copy();t.loc[guard,'weight']=t.loc[guard,'weight'].clip(upper=1.)
            result['phase68j_'+parent+'_'+name]=t
    log('Reconstructing ablations A-I')
    unpruned,_,_=governance(m,part,pruned=False,mult=mult);unref,_,_=governance(m,unpruned,reference=True,pruned=False,mult=mult)
    result['A_selector']=base;result['B_permission']=wrap(m,part,leverage=1.,mult=mult)
    result['C1_soft_governance_only']=wrap(m,unpruned,leverage=1.,mult=mult)
    result['C_soft_filters']=wrap(m,routed(m,unpruned,unref),leverage=1.,mult=mult)
    result['D_pruning']=wrap(m,route,leverage=1.,mult=mult);result['E_exposure_125']=static
    result['E_persistence_bridge']=durable;result['F_ETF_no_cooldown']=etf_overlay(m,durable,days=0);result['G_current']=current
    result['H_replace_selector']=chain('vol_adjusted')[-1];result['I_slow_hysteresis']=chain('slow')[-1]
    for family in ['vol_adjusted','regime_allocation','slow_hysteresis','ensemble']:result['phase2_'+family]=phase2(m,family)
    result['BTC_hold']=e.admit(m,e.target(m,'BTC'));btc=m['raw']['BTC'].close.reindex(m['dates'])
    result['BTC_SMA200']=e.admit(m,e.target(m,pd.Series(np.where(btc>btc.rolling(200).mean(),'BTC','CASH'),index=m['dates'])))
    if include_sensitivities:
        # Explicit non-pruning/governance and route contrasts to avoid claiming
        # that the broad historical family differences isolate a single layer.
        result['S_core_unpruned']=unpruned;result['S_reference_before_NEO_pruning']=unref
        fullref,_,_=governance(m,core,reference=True,pruned=False,mult=mult)
        result['S_NEO_only_not_pruned']=wrap(m,routed(m,core,fullref),leverage=1.,mult=mult)
        ssot,_,_=governance(m,core,reference=True,ssot=True,mult=mult)
        result['S_SSOT_shortlist_current']=etf_overlay(m,persistence(m,wrap(m,routed(m,core,ssot),mult=mult)))
        result['S_economic_route_current']=etf_overlay(m,persistence(m,wrap(m,core,mult=mult)))
        result['S_ETF_extra_day']=etf_overlay(m,durable,availability_delay=1)
        result['S_current_without_ETF']=durable
    return result,meta
