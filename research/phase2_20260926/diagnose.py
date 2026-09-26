"""Frozen benchmark and legacy failure diagnosis; no parameter search."""
import argparse
from collections import defaultdict
from datetime import datetime,timezone
import numpy as np
import pandas as pd
from common import *
from replay import simulate
from signals import Controller

BENCHMARKS={
 'BTC_hold':dict(family='hold'),
 'BTC_SMA200':dict(family='btc_trend'),
 'momentum_weekly':dict(family='simple_momentum',lookback=90,schedule='weekly'),
 'momentum_monthly':dict(family='simple_momentum',lookback=90,schedule='monthly'),
 'CASH':dict(family='cash')}
ABLATIONS=['no_fee','no_slippage','no_funding','zero_cost','no_protection','no_resize','BTC_substitution','entry_plus_one','all_signals_plus_one']
REPRESENTATIVES=['robust_1.25__calmar','robust_1.25__growth','robust_1.25__defensive','aggressive_2.5__calmar','aggressive_3__growth']

def freeze():
    source_contracts();spec=legacy_spec()
    p=HERE/'diagnostic_freeze.json'
    assert not p.exists(),'Immutable freeze exists'
    write(p,dict(created_at=datetime.now(timezone.utc).isoformat(),baseline_commit='9f3bed37ad47c5b952e170aea58671c66fb0c37f',
      benchmarks=BENCHMARKS,ablations=ABLATIONS,representatives=REPRESENTATIVES,costs=spec['costs'],folds=spec['folds'],
      benchmark_cap=3.,benchmark_entry_exposure=1.,benchmark_cap_reason='No borrowed entry notional; passive funding-induced leverage drift is disclosed. All are annual-fold cash-reset hold comparisons, not continuous spot total return.',
      basket='Equal initial equity per asset admitted at fold start minus 2 days. Fixed independent hold sleeves until annual exit, no reallocation to later listings. Intraday DD is a conservative simultaneous-extrema bound.',
      timing='D+2 open; +1 entry stress D+3; all-signal +1 is a separate latency counterfactual, not a feasible D+1 oracle.',
      interpretation='Counterfactual deltas are non-additive. Fees/slippage/funding and mark log contributions are exact additive accounting; regime is ex-ante BTC SMA200 and annualized vol20 > 1.',
      hashes=fingerprints([Path(__file__),HERE/'replay.py',HERE/'common.py',HERE/'signals.py',OLD/'engine.py',OLD/'inputs.zip',ROOT/'source_of_truth/research_objectives_contract.json',ROOT/'source_of_truth/research_phase2_contract.json'])))
    print('Diagnostic protocol frozen',sha(p),flush=True)

def check_freeze():
    spec=read(HERE/'diagnostic_freeze.json')
    for name,h in spec['hashes'].items():assert sha(ROOT/name)==h,name
    return spec

def bench_run(m,cfg):
    return e.stitch([simulate(m,no_risk(),3,start=f['test_start'],end=f['test_end'],controller=Controller(cfg),ledger=True) for f in legacy_spec()['folds']])

def basket_run(m):
    folds=[]
    for fold in legacy_spec()['folds']:
        ix=m.dates.get_loc(fold['test_start'])-2
        assets=[a for k,a in enumerate(m.assets) if m.features['count'][ix,k]>=252]
        sleeves=[simulate(m,no_risk(),3,start=fold['test_start'],end=fold['test_end'],controller=Controller(dict(family='hold',asset=a))) for a in assets]
        rr=np.array([r['rows'] for r in sleeves]);eq=np.cumprod(1+rr[:,:,0],axis=1)
        prior=np.c_[np.ones(len(assets)),eq[:,:-1]];weights=prior/prior.sum(axis=0)
        rows=np.zeros_like(rr[0]);rows[:,0]=(rr[:,:,0]*weights).sum(axis=0)
        for col in [1,2,4,5,6]:rows[:,col]=(rr[:,:,col]*weights).sum(axis=0)
        # This upper bound permits all constituents' daily highs before lows.
        rows[:,3]=1-rows[:,1]/rows[:,2];rows[:,7]=rr[:,:,7].max(axis=0)
        rows[:,8]=rr[:,:,8].max(axis=0)
        attr=np.zeros((len(rows),len(m.assets)));trades=[]
        for day in range(len(rows)):
            contributions=weights[:,day]*rr[:,day,0];net=rows[day,0]
            logs=contributions*(np.log1p(net)/net if abs(net)>1e-14 else 1.)
            for k,a in enumerate(assets):
                ai=m.assets.index(a);attr[day,ai]=logs[k];trades.append([day,ai,k+1,float(logs[k])])
        folds.append(dict(dates=sleeves[0]['dates'],rows=rows,asset_logs=attr,trade_logs=np.array(trades),events=[],signals=[],counters={}))
    return e.stitch(folds)

class Substitute:
    resize=True
    def __init__(self,signals):self.signals={v[0]:v for v in signals}
    def __call__(self,m,p,j,s,i):
        v=self.signals[str(m.dates[i].date())]
        return (m.assets.index('BTC'),v[3]) if v[2]>=0 else (-1,0)

def legacy_replay(m,name,ablation=None):
    spec=legacy_spec();variants={p['id']:p for p in spec['variants']}
    choices=read(OLD/'results/walk_forward_choices.json')[name]
    cap=float(name.split('__')[0].split('_')[1]);runs=[]
    for f in spec['folds']:
        selected=choices[f['id']]['variant']
        if selected is None:r=cash_run(m,f['test_start'],f['test_end'])
        else:
            p=dict(variants[selected]);kw=dict(start=f['test_start'],end=f['test_end'],ledger=True)
            if ablation=='no_protection':p.update(no_risk())
            if ablation=='no_resize':kw['resize_enabled']=False
            if ablation=='entry_plus_one':kw['delay']=1
            if ablation=='all_signals_plus_one':kw['signal_lag']=3
            overrides={}
            for label,key in [('no_fee','fee_bps'),('no_slippage','slippage_bps'),('no_funding','funding_annual_debit')]:
                if ablation in (label,'zero_cost'):overrides[key]=0
            kw['cost_overrides']=overrides
            if ablation=='BTC_substitution':
                base=simulate(m,p,cap,**kw);kw['controller']=Substitute(base['signals'])
            r=simulate(m,p,cap,**kw)
        runs.append(r)
    return e.stitch(runs)

def attribution(m,name,run):
    years=len(run['dates'])/365.25;by_event=defaultdict(lambda:np.zeros(4));by_regime=defaultdict(lambda:np.zeros(4));by_asset=defaultdict(lambda:np.zeros(4))
    for v in run['events']:
        date,asset,episode,growth,cost,turn,kind,*_=v
        vals=np.array([growth,cost,turn,1]);by_event[kind]+=vals;by_asset[asset]+=vals
        j=m.dates.get_loc(date)-2;b=m.assets.index('BTC');f=m.features
        regime=('up' if f['close'][j,b]>f['sma200'][j,b] else 'down')+('_high_vol' if f['vol20'][j,b]>1 else '_normal_vol')
        by_regime[regime]+=vals
    rows=[]
    for group,items in [('event',by_event),('regime',by_regime),('asset',by_asset)]:
        for key,v in items.items():rows.append(dict(policy=name,group=group,key=key,log_growth=v[0],annual_cost_fraction=v[1]/years,annual_turnover=v[2]/years,event_count=int(v[3])))
    # Charge decomposition uses the same cash-debit convention; slippage is not
    # embedded in the raw reference fill. No double counting of price costs.
    trades=sum(v[1] for k,v in by_event.items() if k!='funding');fund=by_event['funding'][1]
    for key,amount in [('fee',trades*4.5/14.5),('slippage',trades*10/14.5),('funding',fund)]:
        rows.append(dict(policy=name,group='cost',key=key,log_growth=None,annual_cost_fraction=amount/years,annual_turnover=0,event_count=0))
    return rows

def run():
    check_freeze();out=HERE/'diagnostics';out.mkdir(exist_ok=True);m=enhanced_market();table=[];attrs=[];checks={}
    for name,cfg in BENCHMARKS.items():
        r=bench_run(m,cfg);write_run(out,name,r,m);table.append(dict(id=name,kind='benchmark',**metrics(r)))
    r=basket_run(m);write_run(out,'equal_weight',r,m);table.append(dict(id='equal_weight',kind='benchmark_conservative_intraday_bound',**metrics(r)))
    policies=read(OLD/'results/walk_forward_choices.json')
    for name in policies:
        r=legacy_replay(m,name);stats=metrics(r);table.append(dict(id=name,kind='legacy',**stats));attrs+=attribution(m,name,r)
        old=pd.read_csv(OLD/f'results/{name}_equity.csv');err=float(np.max(np.abs(old.net_return.to_numpy()-r['rows'][:,0])))
        assert err<1e-13,(name,err);checks[name]=dict(max_return_error=err,legacy_equivalent=True)
        if name in REPRESENTATIVES:write_run(out,name,r,m)
        print('Verified legacy',name,flush=True)
    ablations=[]
    for name in REPRESENTATIVES:
        base=next(t for t in table if t['id']==name)
        for ab in ABLATIONS:
            r=legacy_replay(m,name,ab);s=metrics(r)
            ablations.append(dict(policy=name,ablation=ab,delta_cagr=s['cagr']-base['cagr'],delta_dd=s['max_drawdown']-base['max_drawdown'],**s))
        print('Ablations complete',name,flush=True)
    pd.DataFrame(table).to_csv(out/'benchmarks.csv',index=False)
    pd.DataFrame(attrs).to_csv(out/'attribution.csv',index=False)
    pd.DataFrame(ablations).to_csv(out/'ablations.csv',index=False)
    write(out/'checks.json',checks);write(out/'metrics.json',table)
    print(pd.DataFrame(table)[['id','cagr','max_drawdown','turnover']].to_string(index=False),flush=True)

if __name__=='__main__':
    a=argparse.ArgumentParser();a.add_argument('action',choices=['freeze','run']);args=a.parse_args()
    freeze() if args.action=='freeze' else run()
