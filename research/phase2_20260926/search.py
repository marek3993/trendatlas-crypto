"""Finite phase-2 search. Every partition and validation choice is independent."""
import argparse
import copy
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime,timezone
import sys
import time
from common import *
from replay import simulate
from signals import Controller
sys.path.insert(0,str(ROOT))
from scripts import research_objectives as objectives

FAMILIES=['cross_sectional','dual_momentum','relative_strength','breakout','vol_adjusted','ensemble','regime_allocation','slow_hysteresis']
OVERLAYS={
 'cat4':dict(catastrophic=4,trail=0,tp=0,tp_atr=2,cooldown=3),
 'trail3':dict(catastrophic=0,trail=3,tp=0,tp_atr=2,cooldown=3),
 'tp25_trail3':dict(catastrophic=0,trail=3,tp=.25,tp_atr=2,cooldown=3),
 'tp50_trail3':dict(catastrophic=0,trail=3,tp=.5,tp_atr=2,cooldown=3)}

def variants():
    base=[]
    for family in FAMILIES:
        if family in ('cross_sectional','dual_momentum'):configs=[(n,'monthly') for n in [30,90,180,365]]
        elif family=='relative_strength':configs=[(n,s) for n in [90,180] for s in ['weekly','monthly']]
        elif family=='breakout':configs=[(55,'daily'),(100,'daily')]
        elif family=='ensemble':configs=[(90,'weekly'),(90,'monthly')]
        else:configs=[(90,'monthly' if family!='regime_allocation' else 'weekly'),(180,'monthly' if family!='regime_allocation' else 'weekly')]
        for n,schedule in configs:
            for vol in [.25,.5,1.]:
                p=dict(family=family,lookback=n,schedule=schedule,vol_target=vol)
                if family=='slow_hysteresis':p.update(min_hold=30 if n==90 else 60,hysteresis=.1)
                p['id']=f'{family}_{n}_{schedule}_v{int(vol*100)}';base.append(p)
    return base

def freeze():
    source_contracts();old=legacy_spec();p=HERE/'search_freeze.json'
    assert not p.exists(),'Immutable search freeze exists'
    assert (HERE/'diagnostics/benchmarks.csv').exists(),'Run the diagnostic stage first'
    parts=[dict(id='robust_1.25',mode='robust',cap=1.25,dd_cap=.25)]
    parts += [dict(id=f'aggressive_{cap:g}',mode='aggressive',cap=cap,dd_cap=.35) for cap in [1.25,1.5,2.,2.5,3.]]
    paths=[HERE/n for n in ['common.py','replay.py','signals.py','search.py','test_phase2.py']]
    paths += [OLD/'engine.py',OLD/'inputs.zip',ROOT/'scripts/research_objectives.py',ROOT/'source_of_truth/research_objectives_contract.json',ROOT/'source_of_truth/research_phase2_contract.json']
    write(p,dict(created_at=datetime.now(timezone.utc).isoformat(),variants=variants(),partitions=parts,
      costs=old['costs'],identity=old['identity'],input_members=old['input_members'],folds=old['folds'],
      history_start=old['history_start'],history_end=old['history_end'],development=old['development'],
      budgets_per_partition=dict(base_variants=len(variants()),normal=len(variants()),double_cost=len(variants()),entry_delay=len(variants()),oos_base_policies=10,oos_overlay_policies=4,neighbors_per_base_policy=3,adaptive_retries=0),
      selectors=FAMILIES+['all_growth','all_calmar'],
      selection='Feasibility-first 15-objective Pareto within each family or all families, using preceding calendar validation year only; CAGR>0. Family/all_calmar tie by Calmar, then DD, Sharpe, turnover, lexical ID. all_growth tie by CAGR, DD, turnover, lexical ID. Empty eligible front => CASH.',
      parameters='No fitted labels. Lookbacks approximate crypto calendar months 30/90/180/365 days. Breakout close above previous 55/100-day close high; exit below previous 20/55-day close low. Signal code is hashed verbatim.',
      sizing='Volatility target .25/.5/1 annualized, .9*cap headroom; BTC bear <=.5, fast/slow volatility >1.2/1.3/1.8 limits 1/.75/.5. Rebalance on cadence or material >20% risk reduction; no averaging down. Equal protection/exposure-guard mechanics from phase 1.',
      overlays=OVERLAYS,overlay_base='Each partition all_calmar, chosen solely on no-overlay preceding-year validation; all four overlays paired with identical frozen base choices. Not OOS-selected or used to replace base.',
      neighbors='Three separate replays per base: vol_target x.8, x1.2; nearest different same-family lookback/cadence at same vol target, lexical tie. Pass each if CAGR>0 and >=70% base CAGR and DD<=base DD+.10. Structural grid stability uses all one-axis adjacent variants, never favorable subsets.',
      nomination='A numeric high-return eligible 2020-validation policy; B highest CAGR feasible robust 2020 policy; C highest Calmar feasible aggressive 2020 policy. Freeze before stitched OOS. No sealed historical access; nominal forward parameters are 2026 choices, frozen before OOS metrics.',
      historical_seal=False,history_already_researched=True,diagnostic_sha256=sha(HERE/'diagnostics/benchmarks.csv'),hashes=fingerprints(paths)))
    print('New families frozen:',len(variants()),'variants per partition;',len(parts),'independent budgets;',sha(p),flush=True)

def spec_checked():
    s=read(HERE/'search_freeze.json');source_contracts()
    for name,h in s['hashes'].items():assert sha(ROOT/name)==h,name
    return s

def window_metrics(r,start,end):
    x=e.summarize(r,start,end);mask=(r['dates']>=start)&(r['dates']<=end);d=r['dates'][mask];ret=r['rows'][mask,0]
    quarters=d.to_period('Q');q=[float(np.prod(1+ret[quarters==v])-1) for v in quarters.unique()]
    x.update(fold_returns=q,profitable_fold_fraction=sum(v>0 for v in q)/len(q),worst_fold_return=min(q),parameter_stability=0.)
    return x

def structural_neighbor(p,vs):
    choices=[v for v in vs if v['family']==p['family'] and v['vol_target']==p['vol_target'] and v['id']!=p['id']]
    return min(choices,key=lambda v:(abs(v['lookback']-p['lookback'])/max(1,p['lookback'])+(v['schedule']!=p['schedule']),v['id']))

def partition_grid(part,out):
    spec=spec_checked();fingerprint=sha(HERE/'search_freeze.json');path=out/f"grid_{part['id']}.json"
    if path.exists():
        cache=read(path);assert cache['fingerprint']==fingerprint;return cache['records']
    m=enhanced_market();records={};windows={'development':spec['development']}
    windows.update({str(y):[f'{y}-01-01',f'{y}-12-31'] for y in range(2020,2026)})
    for ix,p in enumerate(spec['variants']):
        normal=simulate(m,no_risk(),part['cap'],start=spec['history_start'],end='2025-12-31',controller=Controller(p))
        doubled=simulate(m,no_risk(),part['cap'],start=spec['history_start'],end='2025-12-31',controller=Controller(p),cost_multiplier=2)
        delayed=simulate(m,no_risk(),part['cap'],start=spec['history_start'],end='2025-12-31',controller=Controller(p),delay=1)
        records[p['id']]={}
        for name,(start,end) in windows.items():
            stats=window_metrics(normal,start,end)
            stats.update(double_cost_cagr=e.summarize(doubled,start,end)['cagr'],delayed_entry_cagr=e.summarize(delayed,start,end)['cagr'])
            records[p['id']][name]=stats
        if ix%15==0:print(part['id'],'base variants',ix+1,'/',len(spec['variants']),flush=True)
    for p in spec['variants']:
        ns=[structural_neighbor(p,spec['variants'])]
        vols=[.25,.5,1.];vi=vols.index(p['vol_target'])
        for k in [vi-1,vi+1]:
            if 0<=k<len(vols):ns += [v for v in spec['variants'] if v['family']==p['family'] and v['lookback']==p['lookback'] and v['schedule']==p['schedule'] and v['vol_target']==vols[k]]
        for name,x in records[p['id']].items():
            count=sum(records[n['id']][name]['cagr']>0 and records[n['id']][name]['cagr']>=.7*x['cagr'] and records[n['id']][name]['max_drawdown']<=x['max_drawdown']+.1 for n in ns)
            x['parameter_stability']=count/len(ns)
    write(path,dict(fingerprint=fingerprint,records=records));return read(path)['records']

def choose(records,part,window,selector,variant_map):
    candidates=[dict(id=k,mode=part['mode'],exposure_cap=part['cap'],development=v[window]) for k,v in records.items()
                if v[window]['cagr']>0 and (selector.startswith('all_') or variant_map[k]['family']==selector)]
    front=objectives.pareto_front(candidates,mode=part['mode'],exposure_cap=part['cap'])
    def key(name):
        m=records[name][window]
        if selector=='all_growth':return (-m['cagr'],m['max_drawdown'],m['turnover'],name)
        return (-m['calmar'],m['max_drawdown'],-m['sharpe'],m['turnover'],name)
    return min(front,key=key) if front else None

def replay_policy(m,part,choices,vm,spec,overlay=None,cost_multiplier=1,delay=0,neighbor=None,ledger=False):
    runs=[];foldstats=[]
    for f in spec['folds']:
        selected=choices[f['id']]
        if selected is None:r=cash_run(m,f['test_start'],f['test_end'])
        else:
            p=copy.deepcopy(vm[selected])
            if neighbor in ('vol_low','vol_high'):p['vol_target']*=.8 if neighbor=='vol_low' else 1.2
            elif neighbor=='structure':p=structural_neighbor(p,spec['variants'])
            risk=OVERLAYS[overlay] if overlay else no_risk()
            r=simulate(m,risk,part['cap'],start=f['test_start'],end=f['test_end'],controller=Controller(p),cost_multiplier=cost_multiplier,delay=delay,ledger=ledger)
        runs.append(r);foldstats.append(dict(fold=f['id'],variant=selected,**e.summarize(r)))
    return e.stitch(runs),foldstats

def search(out,workers):
    spec=spec_checked();out.mkdir(parents=True,exist_ok=True);vm={p['id']:p for p in spec['variants']}
    with ProcessPoolExecutor(max_workers=workers) as pool:
        jobs={p['id']:pool.submit(partition_grid,p,out) for p in spec['partitions']}
        records={k:v.result() for k,v in jobs.items()}
    selections={};development={};valrows=[]
    for part in spec['partitions']:
        rr=records[part['id']]
        for variant,windows in rr.items():
            for window,x in windows.items():valrows.append(dict(partition=part['id'],variant=variant,window=window,**{k:v for k,v in x.items() if not isinstance(v,list)}))
        for selector in spec['selectors']:
            name=part['id']+'__'+selector
            selections[name]={f['id']:choose(rr,part,str(int(f['id'])-1),selector,vm) for f in spec['folds']}
            first=selections[name]['2021'];development[name]=rr[first]['2020'] if first else None
    write(out/'choices_before_oos.json',selections)
    pd.DataFrame(valrows).to_csv(out/'validation_scores.csv',index=False)
    eligible=[n for n,v in development.items() if v]
    robust=[n for n in eligible if n.startswith('robust')];aggr=[n for n in eligible if n.startswith('aggressive')]
    a=[n for n in eligible if not objectives.high_return_issues(development[n],objectives.load_contract(),sealed=False)]
    nominations=dict(A=min(a,key=lambda n:(-development[n]['calmar'],n)) if a else None,
       B=min(robust,key=lambda n:(-development[n]['cagr'],development[n]['max_drawdown'],n)) if robust else None,
       C=min(aggr,key=lambda n:(-development[n]['calmar'],development[n]['max_drawdown'],n)) if aggr else None,
       basis='2020 validation only; forward parameters use frozen 2026 choice; no historical seal',search_sha256=sha(HERE/'search_freeze.json'))
    nominations['forward_parameters']={n:vm.get(selections[n]['2026']) for n in {nominations[k] for k in ['A','B','C']}-{None}}
    target=out/'nominees_before_oos.json'
    if target.exists():assert read(target)==nominations
    else:write(target,nominations)
    print('Nominations frozen before OOS',nominations,flush=True)
    m=enhanced_market();policies=[];folds=[];neighbors=[]
    for part in spec['partitions']:
        jobs=[(s,None) for s in spec['selectors']]+[('all_calmar',overlay) for overlay in OVERLAYS]
        for selector,overlay in jobs:
            base=part['id']+'__'+selector;name=base+('__'+overlay if overlay else '')
            choices=selections[base]
            normal,ff=replay_policy(m,part,choices,vm,spec,overlay=overlay,ledger=True);stats=metrics(normal)
            doubled,_=replay_policy(m,part,choices,vm,spec,overlay=overlay,cost_multiplier=2)
            delayed,_=replay_policy(m,part,choices,vm,spec,overlay=overlay,delay=1)
            passes=0
            for neighbor in ['vol_low','vol_high','structure']:
                r,_=replay_policy(m,part,choices,vm,spec,overlay=overlay,neighbor=neighbor);met=metrics(r)
                ok=met['cagr']>0 and met['cagr']>=.7*stats['cagr'] and met['max_drawdown']<=stats['max_drawdown']+.1
                passes+=ok;neighbors.append(dict(policy=name,neighbor=neighbor,passed=bool(ok),**{k:v for k,v in met.items() if not isinstance(v,list)}))
            stats.update(double_cost_cagr=metrics(doubled)['cagr'],delayed_entry_cagr=metrics(delayed)['cagr'],parameter_stability=passes/3)
            candidate=dict(id=name,mode=part['mode'],exposure_cap=part['cap'],oos=stats)
            issues=objectives.feasibility(candidate,stats,objectives.load_contract())
            high=objectives.high_return_issues(stats,objectives.load_contract(),sealed=False)
            if passes<3:high.append('parameter_neighbors')
            row=dict(id=name,partition=part['id'],selector=selector,overlay=overlay,cap=part['cap'],mode=part['mode'],oos=stats,development=development[base],
                     feasible=not issues,feasibility_issues=issues,high_return_failures=high,accepted_high_return=False,counters=normal['counters'])
            policies.append(row);folds += [dict(policy=name,**v) for v in ff]
            write_run(out,name,normal,m)
            for label,r in [('double',doubled),('delay',delayed)]:
                pd.DataFrame(dict(date=r['dates'],net_return=r['rows'][:,0])).to_csv(out/f'{name}_{label}.csv',index=False)
            print(name,'CAGR',round(stats['cagr']*100,2),'DD',round(stats['max_drawdown']*100,2),'feasible',not issues,flush=True)
    # OOS comparison is descriptive and cannot reselect a frozen nominee.
    directions=objectives.load_contract()['fitness']['objectives']
    def dominates(a,b):
        diffs=[(a['oos'][k]-b['oos'][k])*(1 if d=='max' else -1) for k,d in directions.items()]
        return all(v>=0 for v in diffs) and any(v>0 for v in diffs)
    for p in policies:
        peers=[v for v in policies if v['partition']==p['partition'] and v['feasible'] and v['overlay'] is None]
        p['pareto']=p['feasible'] and p['overlay'] is None and not any(dominates(v,p) for v in peers)
    write(out/'results.json',dict(policies=policies,nominations=nominations,A=None,D=True,historical_seal=False))
    pd.DataFrame([dict(policy=p['id'],partition=p['partition'],selector=p['selector'],overlay=p['overlay'],feasible=p['feasible'],pareto=p['pareto'],**{k:v for k,v in p['oos'].items() if not isinstance(v,list)}) for p in policies]).to_csv(out/'pareto_table.csv',index=False)
    pd.DataFrame(folds).to_csv(out/'oos_folds.csv',index=False);pd.DataFrame(neighbors).to_csv(out/'neighbors.csv',index=False)

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('action',choices=['freeze','run']);parser.add_argument('--workers',type=int,default=6);parser.add_argument('--out',type=Path,default=HERE/'results');args=parser.parse_args()
    if args.action=='freeze':freeze()
    else:
        resolved=args.out.resolve();assert resolved.is_relative_to(HERE) or resolved.is_relative_to(ROOT/'scratch')
        search(resolved,args.workers)
