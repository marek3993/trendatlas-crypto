"""Run the pre-registered six-partition search and nested chronological OOS.

Search outputs are research evidence only. Sealed history is explicitly absent.
"""
from __future__ import annotations
import argparse
from concurrent.futures import ProcessPoolExecutor
import copy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time
import numpy as np
import pandas as pd
import engine
from prepare import write_json,digest

HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1]
sys.path.insert(0,str(ROOT))
from scripts import research_objectives as objectives


def code_hashes():
    paths=[HERE/'engine.py',HERE/'run.py',HERE/'prepare.py',HERE/'test_engine.py',
           ROOT/'scripts/research_objectives.py',ROOT/'source_of_truth/research_objectives_contract.json',HERE/'pre_registration.json']
    return {p.relative_to(ROOT).as_posix():digest(p.read_bytes()) for p in paths}


def bounded_out(path):
    p=path.resolve()
    if not (p.is_relative_to(HERE) or p.is_relative_to(ROOT/'scratch')):raise ValueError('Research output must stay in research folder or scratch')
    p.mkdir(parents=True,exist_ok=True);return p


def quarter_returns(run,start,end):
    dates=run['dates'];r=run['rows'][:,0];answer=[]
    periods=dates.to_period('Q')
    for q in periods[(dates>=start)&(dates<=end)].unique():
        mask=(periods==q)&(dates>=start)&(dates<=end)
        answer.append(float(np.prod(1+r[mask])-1))
    return answer


def cagr_interval(run,start,end):
    mask=(run['dates']>=start)&(run['dates']<=end)
    n=int(mask.sum());growth=np.prod(1+run['rows'][mask,0])
    return float(growth**(365.25/n)-1)


def metric_windows(normal,stress,delayed,spec):
    windows={'development':spec['development']}
    windows.update({str(y):[f'{y}-01-01',f'{y}-12-31'] for y in range(2020,2026)})
    result={}
    for name,(start,end) in windows.items():
        m=engine.summarize(normal,start,end);folds=quarter_returns(normal,start,end)
        m.update(fold_returns=folds,profitable_fold_fraction=sum(x>0 for x in folds)/len(folds),worst_fold_return=min(folds),
                 double_cost_cagr=cagr_interval(stress,start,end),delayed_entry_cagr=cagr_interval(delayed,start,end),parameter_stability=0.)
        result[name]=m
    return result


def add_grid_stability(records,variants):
    lookup={(p['momentum'],p['trend'],p['vol_target'],p['name']):p['id'] for p in variants}
    for p in variants:
        neighbors=[]
        for key,grid in [('momentum',[21,63,126]),('vol_target',[.2,.4,.6])]:
            ix=grid.index(p[key])
            for nx in [ix-1,ix+1]:
                if 0<=nx<len(grid):
                    q=dict(p);q[key]=grid[nx];neighbors.append(lookup[(q['momentum'],q['trend'],q['vol_target'],q['name'])])
        for window,m in records[p['id']].items():
            passed=sum(records[n][window]['cagr']>0 and records[n][window]['cagr']>=.7*m['cagr']
                       and records[n][window]['max_drawdown']<=m['max_drawdown']+.10 for n in neighbors)
            m['parameter_stability']=passed/len(neighbors)


def choose(records,part,window,selector):
    candidates=[dict(id=name,mode=part['mode'],exposure_cap=part['cap'],development=metrics[window])
                for name,metrics in records.items() if metrics[window]['cagr']>0 and not metrics[window]['bankrupt']]
    front=objectives.pareto_front(candidates,mode=part['mode'],exposure_cap=part['cap'])
    if not front:return None,[]
    def key(name):
        m=records[name][window]
        if selector=='growth':return (-m['cagr'],m['max_drawdown'],m['turnover'],name)
        if selector=='calmar':return (-m['calmar'],m['max_drawdown'],-m['sharpe'],m['turnover'],name)
        return (m['max_drawdown'],-m['cagr'],m['turnover'],name)
    return min(front,key=key),front


def cash_run(m,start,end):
    ix=(m.dates>=start)&(m.dates<=end);n=int(ix.sum());rows=np.zeros((n,9));rows[:,1:3]=1
    return dict(dates=m.dates[ix],rows=rows,asset_logs=np.zeros((n,len(m.assets))),trade_logs=np.zeros((0,4)),events=[],signals=[],counters={})


def ensure_momentum(m,n):
    key='mom'+str(n)
    if key not in m.features:
        c=m.features['close'];a=np.full_like(c,np.nan);a[n:]=c[n:]/c[:-n]-1;m.features[key]=a


def replay_policy(m,part,choices,variant_map,spec,*,cost_multiplier=1,delay=0,perturb=None,ledger=False):
    runs=[];fold_results=[]
    for fold in spec['folds']:
        selected=choices[fold['id']]['variant']
        if selected is None:run=cash_run(m,fold['test_start'],fold['test_end'])
        else:
            p=copy.deepcopy(variant_map[selected])
            if perturb:
                axis,factor=perturb
                if axis=='risk':
                    for field in ['catastrophic','trail','tp_atr']:p[field]*=factor
                elif axis=='momentum':p['momentum']=max(2,round(p['momentum']*factor));ensure_momentum(m,p['momentum'])
                elif axis=='vol_target':p['vol_target']*=factor
            run=engine.simulate(m,p,part['cap'],start=fold['test_start'],end=fold['test_end'],
                                cost_multiplier=cost_multiplier,delay=delay,ledger=ledger)
        fold_results.append(dict(fold=fold['id'],variant=selected,**engine.summarize(run)))
        runs.append(run)
    joined=engine.stitch(runs);stats=engine.summarize(joined)
    folds=[x['total_return'] for x in fold_results]
    stats.update(fold_returns=folds,profitable_fold_fraction=sum(x>0 for x in folds)/len(folds),worst_fold_return=min(folds))
    return joined,stats,fold_results


def write_run(out,name,run,m):
    frame=pd.DataFrame(run['rows'],columns=['net_return','event_low_ratio','event_high_ratio','internal_drawdown','turnover','cost_fraction','max_exposure','bankrupt','activity'])
    frame.insert(0,'date',run['dates'].strftime('%Y-%m-%d'));frame['equity']=(1+frame.net_return).cumprod()
    frame.to_csv(out/f'{name}_equity.csv',index=False,lineterminator='\n')
    pd.DataFrame(run['events'],columns=['date','asset','episode','log_growth','cost_fraction','turnover','event','price','quantity_change','equity_after']).to_csv(out/f'{name}_events.csv',index=False,lineterminator='\n')
    pd.DataFrame(run['signals'],columns=['fill_day','source_day','target_asset_index','target_exposure']).to_csv(out/f'{name}_signals.csv',index=False,lineterminator='\n')


def real_audit(m,part,choices,variant_map,spec,run,stats):
    """Actually replay prefixes and future perturbations, inspect fills/lineage.
    Venue/PIT-universe limitations remain failures, never fabricated passes.
    """
    prefix_ok=True;future_ok=True;checks=0
    for fold in spec['folds']:
        selected=choices[fold['id']]['variant']
        if selected is None:continue
        p=variant_map[selected];cut=pd.Timestamp(fold['test_start'])+pd.Timedelta(days=120)
        end=min(cut,pd.Timestamp(fold['test_end']));stop=int(m.dates.searchsorted(end,side='right'))
        reference=engine.simulate(m,p,part['cap'],start=fold['test_start'],end=str(end.date()))
        truncated=engine.Market(m.dates[:stop],m.assets,m.prices[:stop].copy(),{k:v[:stop].copy() for k,v in m.features.items()})
        # Recompute indicators from the truncated raw data, not copied features.
        raw={a:pd.DataFrame(m.prices[:stop,j],index=m.dates[:stop],columns=['open','high','low','close']).dropna() for j,a in enumerate(m.assets)}
        rebuilt=engine.market_from_frames(raw)
        probe=engine.simulate(rebuilt,p,part['cap'],start=fold['test_start'],end=str(end.date()))
        prefix_ok &= np.array_equal(reference['rows'],probe['rows']) and reference['signals']==probe['signals']
        raw_full={a:pd.DataFrame(m.prices[:,j],index=m.dates,columns=['open','high','low','close']).dropna() for j,a in enumerate(m.assets)}
        for frame in raw_full.values():frame.loc[frame.index>end]*=3.17
        altered=engine.market_from_frames(raw_full)
        probe=engine.simulate(altered,p,part['cap'],start=fold['test_start'],end=str(end.date()))
        future_ok &= np.array_equal(reference['rows'],probe['rows']) and reference['signals']==probe['signals'];checks+=1
    timestamp_ok=all(pd.Timestamp(fill)-pd.Timestamp(src)>=pd.Timedelta(days=2) for fill,src,_,_ in run['signals'])
    identity_ok=True;bad=[]
    for event in run['events']:
        date,asset,ep,growth,cost,turnover,kind,price,qty,eq=event
        if asset not in m.assets:identity_ok=False;bad.append([date,asset]);continue
        i=m.dates.get_loc(date);a=m.assets.index(asset);o,h,l,c=m.prices[i,a]
        if price and not l-1e-8<=price<=h+1e-8:identity_ok=False;bad.append([date,asset,price,l,h])
    return dict(prefix_replay_invariance=bool(prefix_ok),future_data_perturbation_invariance=bool(future_ok),
        prefix_and_perturbation_replays=checks*2,same_day_filter_rejection=timestamp_ok,
        signal_publication_timestamps='explicit conservative availability assumption; not historically observed',
        asset_price_fill_lineage=identity_ok,lineage_errors=bad,
        pnl_reconciliation=stats['log_reconciliation_error']<1e-8 and stats['trade_log_reconciliation_error']<1e-8,
        point_in_time_universe=False,reason_universe='Fixed survivor universe with causal listing admission; no delisted-history reconstruction.',
        gap_and_intrabar_fill_order='both OHLC paths evaluated; worse terminal account equity used',
        cost_funding_alignment='conservative daily opening-notional debit proxy; not observed venue funding',
        venue_cost_coverage=False,expanded_audit_passed=False,
        reason='Price causality can pass, but historical venue fills/funding and independent historical universe are not proved.')


def run_search(m,spec,part,out,cache_root,fingerprint):
    cache=cache_root/(part['id']+'.json')
    if cache.exists():
        saved=json.loads(cache.read_text())
        if saved['fingerprint']==fingerprint:
            print('verified cache',part['id'],flush=True);return saved['records']
        raise ValueError('Stale cache; choose a new empty cache directory')
    records={};begun=time.perf_counter()
    for index,p in enumerate(spec['variants']):
        nominal=engine.simulate(m,p,part['cap'],end='2025-12-31')
        doubled=engine.simulate(m,p,part['cap'],end='2025-12-31',cost_multiplier=2)
        delayed=engine.simulate(m,p,part['cap'],end='2025-12-31',delay=1)
        records[p['id']]=metric_windows(nominal,doubled,delayed,spec)
        if (index+1)%27==0:print(f'{part["id"]}: {index+1}/324 nominal + 2 stresses; elapsed {time.perf_counter()-begun:.1f}s',flush=True)
    add_grid_stability(records,spec['variants'])
    write_json(cache,dict(fingerprint=fingerprint,records=records))
    # The evidence boundary uses JSON-native finite numbers. In-memory numpy
    # scalars (notably Calmar) must take the same path as a cached run; the strict
    # objectives validator intentionally rejects foreign numeric/boolean types.
    return json.loads(cache.read_text())['records']


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--out',type=Path,default=HERE/'results')
    parser.add_argument('--cache',type=Path,default=ROOT/'scratch/causal_search_cache');args=parser.parse_args()
    out=bounded_out(args.out);cache=bounded_out(args.cache);spec,contract=engine.load_spec()
    hashes=code_hashes();fingerprint=digest(json.dumps(hashes,sort_keys=True).encode())
    freeze=out/'implementation_freeze.json'
    payload=dict(code_sha256=hashes,search_fingerprint=fingerprint,
                 input_sha256=spec['input_bundle_sha256'],contract_sha256=spec['contract_sha256'],
                 source_commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
                 availability='D close +1 second; execution D+2 open; delayed D+3 open',
                 funding='12% annual debit on full opening held notional, charged before intraday path even if position exits later that day; explicit conservative proxy',
                 validation_stability='Past validation-year quarterly net returns; outer fold stability uses six annual OOS returns',
                 numpy=np.__version__,pandas=pd.__version__,frozen_at_utc=datetime.now(timezone.utc).isoformat())
    if freeze.exists():
        old=json.loads(freeze.read_text());assert old['search_fingerprint']==fingerprint,'Implementation changed after first run'
    else:write_json(freeze,payload)
    m=engine.load_market();variant_map={p['id']:p for p in spec['variants']}
    print('Verified inputs and implementation freeze; market shape',m.prices.shape,flush=True)
    records_by_part={};selection={};development={};rows=[]
    # Independent frozen budgets; no information is shared between workers.
    with ProcessPoolExecutor(max_workers=6) as pool:
        futures={part['id']:pool.submit(run_search,m,spec,part,out,cache,fingerprint) for part in spec['partitions']}
        for part in spec['partitions']:
            records_by_part[part['id']]=futures[part['id']].result()
    for part in spec['partitions']:
        records=records_by_part[part['id']]
        for p_id,windows in records.items():
            for window,metrics in windows.items():
                rows.append(dict(partition=part['id'],variant=p_id,window=window,**{k:v for k,v in metrics.items() if not isinstance(v,list)}))
        for selector in spec['selectors']:
            name=part['id']+'__'+selector;selection[name]={}
            for fold in spec['folds']:
                choice,front=choose(records,part,str(int(fold['id'])-1),selector)
                selection[name][fold['id']]=dict(variant=choice,validation_start=fold['validation_start'],validation_end=fold['validation_end'],pareto_size=len(front))
            first=selection[name]['2021']['variant']
            development[name]=records[first]['2020'] if first else None
    pd.DataFrame(rows).to_csv(out/'validation_scores.csv',index=False,lineterminator='\n')
    write_json(out/'walk_forward_choices.json',selection)
    # This record precedes OOS portfolio metrics; there is no historical seal.
    eligible=[name for name,met in development.items() if met]
    robust=[n for n in eligible if n.startswith('robust_')]
    aggressive=[n for n in eligible if n.startswith('aggressive_')]
    a=[n for n in eligible if not objectives.high_return_issues(development[n],contract,sealed=False)]
    nominee_a=min(a,key=lambda n:(development[n]['max_drawdown']>.2,development[n]['max_drawdown']>.3,-development[n]['calmar'],-development[n]['sharpe'],-development[n]['cagr'],n)) if a else None
    nominee_b=min(robust,key=lambda n:(-development[n]['cagr'],development[n]['max_drawdown'],n)) if robust else None
    nominee_c=min(aggressive,key=lambda n:(-development[n]['calmar'],development[n]['max_drawdown'],n)) if aggressive else None
    nominations=dict(A=nominee_a,B=nominee_b,C=nominee_c,selection_source='2020 validation only; before OOS metric calculation',
                     search_fingerprint=fingerprint,history_sealed=False,parameters_for_forward={})
    for n in {nominee_a,nominee_b,nominee_c}-{None}:
        chosen=selection[n]['2026']['variant'];nominations['parameters_for_forward'][n]=variant_map[chosen] if chosen else None
    nomination_path=out/'nominees_before_oos.json'
    if nomination_path.exists():assert json.loads(nomination_path.read_text())==nominations
    else:write_json(nomination_path,nominations)
    print('Nominees frozen before OOS metric evaluation',dict(A=nominee_a,B=nominee_b,C=nominee_c),flush=True)
    policies=[];fold_rows=[];audits={};neighbor_rows=[]
    for part in spec['partitions']:
        for selector in spec['selectors']:
            name=part['id']+'__'+selector;choices=selection[name]
            normal,metrics,folds=replay_policy(m,part,choices,variant_map,spec,ledger=True)
            doubled,double_metrics,_=replay_policy(m,part,choices,variant_map,spec,cost_multiplier=2)
            delayed,delay_metrics,_=replay_policy(m,part,choices,variant_map,spec,delay=1)
            passing=0
            for axis in ['risk','momentum','vol_target']:
                for factor in [.8,1.2]:
                    _,nm,_=replay_policy(m,part,choices,variant_map,spec,perturb=(axis,factor))
                    ok=nm['cagr']>0 and nm['cagr']>=.7*metrics['cagr'] and nm['max_drawdown']<=metrics['max_drawdown']+.1
                    passing+=ok;neighbor_rows.append(dict(policy=name,axis=axis,factor=factor,passed=bool(ok),cagr=nm['cagr'],max_drawdown=nm['max_drawdown']))
            metrics.update(double_cost_cagr=double_metrics['cagr'],delayed_entry_cagr=delay_metrics['cagr'],parameter_stability=passing/6)
            failures=objectives.high_return_issues(metrics,contract,sealed=False)
            if passing<6:failures.append('parameter_neighbors')
            if metrics['max_realized_exposure']>part['cap']+1e-9:failures.append('exposure_cap')
            feasible=metrics['max_drawdown']<=part['dd_cap'] and metrics['max_realized_exposure']<=part['cap']+1e-9 and not metrics['bankrupt']
            policy=dict(id=name,mode=part['mode'],cap=part['cap'],selector=selector,oos=metrics,development=development[name],
                        risk_feasible=feasible,oos_numeric_high_return_passed=not failures,high_return_failures=failures,
                        sealed_status='NOT_AVAILABLE_FORWARD_REQUIRED',accepted_high_return_winner=False,counters=normal['counters'])
            policies.append(policy)
            for f in folds:fold_rows.append(dict(policy=name,**{k:v for k,v in f.items() if not isinstance(v,list)}))
            write_run(out,name,normal,m)
            for scenario,r in [('double_cost',doubled),('delayed',delayed)]:
                pd.DataFrame(dict(date=r['dates'].strftime('%Y-%m-%d'),net_return=r['rows'][:,0],equity=np.cumprod(1+r['rows'][:,0]))).to_csv(out/f'{name}_{scenario}.csv',index=False,lineterminator='\n')
            # Run extended structural audits for all 18, including any high result.
            audits[name]=real_audit(m,part,choices,variant_map,spec,normal,metrics)
            print(name,'OOS',round(metrics['cagr']*100,2),'DD',round(metrics['max_drawdown']*100,2),'feasible',feasible,flush=True)
    pd.DataFrame(fold_rows).to_csv(out/'oos_folds.csv',index=False,lineterminator='\n')
    pd.DataFrame(neighbor_rows).to_csv(out/'parameter_neighbors.csv',index=False,lineterminator='\n')
    write_json(out/'expanded_audits.json',audits)
    objectives_map=contract['fitness']['objectives']
    def dominates(a,b):
        x=[(a['oos'][k]-b['oos'][k])*(1 if d=='max' else -1) for k,d in objectives_map.items()]
        return all(v>=0 for v in x) and any(v>0 for v in x)
    for policy in policies:
        group=[p for p in policies if p['mode']==policy['mode'] and p['risk_feasible']]
        policy['descriptive_oos_pareto']=policy['risk_feasible'] and not any(dominates(other,policy) for other in group)
    robust=[p for p in policies if p['mode']=='robust' and p['risk_feasible']]
    aggressive=[p for p in policies if p['mode']=='aggressive' and p['descriptive_oos_pareto']]
    best_b=max(robust,key=lambda p:(p['oos']['cagr'],-p['oos']['max_drawdown']))['id'] if robust else None
    best_c=max(aggressive,key=lambda p:(p['oos']['calmar'],-p['oos']['max_drawdown']))['id'] if aggressive else None
    result=dict(scope='conditional historical price/cost proxy research; no sealed proof',policies=policies,
                nominal_trials=1944,stress_replays=3888,policy_neighbor_replays=108,
                A=None,B_observed_best_robust=best_b,C_observed_aggressive_pareto=best_c,D=True,
                forward_nominees=nominations,observed_comparison_is_not_forward_reselection=True,
                oos_numeric_passes=[p['id'] for p in policies if p['oos_numeric_high_return_passed']],
                limitations=spec['limitations'],no_merge=True,no_deploy=True,no_orders=True)
    write_json(out/'results.json',result)
    table=[dict(policy=p['id'],mode=p['mode'],cap=p['cap'],risk_feasible=p['risk_feasible'],pareto=p['descriptive_oos_pareto'],
                **{k:v for k,v in p['oos'].items() if not isinstance(v,list)}) for p in policies]
    pd.DataFrame(table).to_csv(out/'pareto_table.csv',index=False,lineterminator='\n')
    manifest={p.name:digest(p.read_bytes()) for p in sorted(out.iterdir()) if p.is_file() and p.name not in ('reproduction_manifest.json','implementation_freeze.json')}
    write_json(out/'reproduction_manifest.json',dict(search_fingerprint=fingerprint,files=manifest))
    print(json.dumps({k:result[k] for k in ['A','B_observed_best_robust','C_observed_aggressive_pareto','D','oos_numeric_passes']}),flush=True)


if __name__=='__main__':main()
