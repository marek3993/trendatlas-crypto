"""Frozen-budget development search, nominee freeze, then chronological OOS."""
import io,json,platform,time,zipfile
from pathlib import Path
import numpy as np
import pandas as pd
from common import HERE,ROOT,SPEC,digest,write,candidate_id,protected
import market,signals,ledger,designer,evaluate as ev

OUT=HERE/'results'

def logrow(path,row):
    with path.open('a',encoding='utf-8') as f:f.write(json.dumps(row,sort_keys=True,allow_nan=False,default=str)+'\n')

def save_run(z,name,run):
    z.writestr(name+'/bars.csv',run['daily'].drop(columns='path').to_csv(index_label='bar_open',float_format='%.14g'))
    z.writestr(name+'/episodes.csv',pd.DataFrame(run['episodes']).to_csv(index=False,float_format='%.14g'))
    z.writestr(name+'/fills.csv',pd.DataFrame(run['fills']).to_csv(index=False,float_format='%.14g'))

def nominate(rows):
    valid=[r for r in rows if ev.feasible(r)];front=ev.fronts(valid)[0] if valid else []
    a=sorted(front,key=lambda r:(0 if r['mdd']<=.2 else 1 if r['mdd']<=.3 else 2,-r['calmar'],-r['sharpe'],-r['cagr'],r['turnover'],r['candidate_id']))
    b=sorted([r for r in front if r['mdd']<=.25],key=lambda r:(-r['cagr'],r['mdd'],r['turnover'],r['candidate_id']))
    c=sorted(front,key=lambda r:(-r['calmar'],r['mdd'],-r['sharpe'],r['turnover'],r['candidate_id']))
    allvalid=[r for r in rows if r['status']=='VALID'];aggressive=sorted(ev.fronts(allvalid)[0],key=lambda r:(-r['cagr'],r['mdd'],r['candidate_id'])) if allvalid else []
    return dict(A=a[0] if a else None,B=b[0] if b else None,C=c[0] if c else None,aggressive_diagnostic=aggressive[0] if aggressive else None)

def baseline_pass(metrics):
    return metrics['cagr']>0 and metrics['mdd']<=.35 and metrics['sharpe']>=.75 and metrics['double_cost_cagr']>0 and metrics['delayed_cagr']>0 and metrics['profitable_folds']/metrics['fold_count']>=.75

def capital(runs):return float(np.prod([r['daily'].equity.iloc[-1] for r in runs.values()]))

def main():
    started=time.time();before=protected();OUT.mkdir(exist_ok=True)
    if (OUT/'freeze.json').exists():raise RuntimeError('Immutable run exists; archive attempts explicitly before a corrected rerun')
    tracked=['contract.json','market_inputs.zip','cohort.json','venue_notices.json','listing_evidence.json']+[p.name for p in HERE.glob('*.py')]
    freeze=dict(created_utc=pd.Timestamp.now(tz='UTC').isoformat(),source_commit=SPEC['source_commit'],hashes={p:digest(HERE/p) for p in tracked},parent_ledger_sha256=digest(ROOT/'research/archeology_20260926/engine.py'),python=platform.python_version(),numpy=np.__version__,pandas=pd.__version__,sealed_opened=False,search_budget=330)
    write(OUT/'freeze.json',freeze)
    market.evidence();designer_=designer.Designer();alltrials=[];champions={};final_rows=[];neighbor_rows=[];baselines=[];generation_log=[]
    # Baselines run before the population search; their complete results remain
    # explicitly scoped to development, with no rule changes based on them.
    for origin in SPEC['evolution']['origins']:
        year=origin-1;m=market.load(f'{year}-12-31 20:00:00');print(f'Origin {origin}: only development through {year}-12-31 loaded',flush=True)
        for name in ['CASH','BTC_hold','BTC_SMA200']:
            try:
                r=ledger.summarize(ev.replay(m,signals.baseline(m,name),year));baselines.append(dict(name=name,year=year,scope='development',status='VALID',**r))
            except ValueError as exc:baselines.append(dict(name=name,year=year,scope='development',status='REJECT_DATA_OR_EXECUTION',reason=str(exc)))
        for fi,family in enumerate(['A','B','C']):
            seed=SPEC['evolution']['seed']+origin*100+fi;pop=designer.initial(family,seed);cache={}
            for generation in range(4):
                for cfg in pop:
                    cid=candidate_id(cfg)
                    if cid not in cache:
                        row=ev.evaluate(m,cfg,year);row.update(origin=origin,generation=generation);cache[cid]=row;alltrials.append(row);logrow(OUT/'development.jsonl',row)
                ranked=ev.survivors([cache[candidate_id(c)] for c in pop],6)
                generation_log.append(dict(origin=origin,family=family,generation=generation,population=[candidate_id(c) for c in pop],survivors=[r['candidate_id'] for r in ranked],unique_evaluations=len(cache)))
                print(f'  {family} generation {generation+1}: {len(cache)} unique; valid={sum(r["status"]=="VALID" for r in cache.values())}; feasible={sum(ev.feasible(r) for r in cache.values())}',flush=True)
                if generation<3:
                    kept=[r['candidate'] for r in ranked];new=designer_.propose(family,list(cache.values()),kept,set(cache),seed+generation);pop=kept+new
            champion=ev.champion(list(cache.values()));champions[(origin,family)]=champion
            write(OUT/f'origin_{origin}_{family}_frozen.json',dict(frozen_before_oos=True,validation_year=year,champion=champion,development_pareto=ev.fronts([r for r in cache.values() if r['status']=='VALID'])[0] if any(r['status']=='VALID' for r in cache.values()) else []))
            if origin==2026:final_rows+=list(cache.values())
            # Frozen adjacent-neighbor checks never feed survival/mutations.
            for cfg in designer.neighbors(champion['candidate']):
                row=ev.evaluate(m,cfg,year,scope='validation_neighbor');row.update(parent_id=champion['candidate_id'],origin=origin);neighbor_rows.append(row)
    assert len(alltrials)<=330
    write(OUT/'designer_log.json',dict(api_calls=designer_.calls,events=designer_.log));write(OUT/'generations.json',generation_log)
    write(OUT/'development_baselines.json',baselines);write(OUT/'neighbors.json',neighbor_rows)
    nominations=nominate(final_rows)
    write(OUT/'finalists_frozen.json',dict(frozen_utc=pd.Timestamp.now(tz='UTC').isoformat(),scope='2025 development selection for prospective 2026-09-27 onward',forward_opened=False,slots=nominations,all_final_development=final_rows,contract_sha256=digest(HERE/'contract.json')))
    # No design or search is allowed after this event. All four test years are
    # opened only for already frozen, prior-year-selected nominees.
    logrow(OUT/'access_log.jsonl',dict(event='all_fold_and_forward_nominees_frozen',sha256=digest(OUT/'finalists_frozen.json')))
    m=market.load();folds=[];ablations=[];family_runs={f:{} for f in ['A','B','C']};double_runs={f:{} for f in family_runs};delay_runs={f:{} for f in family_runs};ensemble_runs={};ensemble_members={};baseline_runs={n:{} for n in ['CASH','BTC_hold','BTC_SMA200']};errors=[]
    with zipfile.ZipFile(OUT/'ledgers.zip','w',zipfile.ZIP_DEFLATED) as z:
        for year in [2022,2023,2024,2025]:
            logrow(OUT/'access_log.jsonl',dict(event='outer_oos_opened',year=year,nominee_hashes={f:digest(OUT/f'origin_{year}_{f}_frozen.json') for f in family_runs}))
            eligible_members=[]
            for family in family_runs:
                if len(family_runs[family])>=2:
                    prior,_=ev.stitch(family_runs[family]);d,_=ev.stitch(double_runs[family]);late,_=ev.stitch(delay_runs[family]);prior.update(double_cost_cagr=d['cagr'],delayed_cagr=late['cagr'])
                    if baseline_pass(prior):eligible_members.append(family)
            print('Opening frozen OOS fold '+str(year),flush=True);targets={}
            for family in family_runs:
                cfg=champions[(year,family)]['candidate'];scale=capital(family_runs[family]);ds=capital(double_runs[family]);ls=capital(delay_runs[family])
                row,run=ev.evaluate(m,cfg,year,scope='outer_oos',keep=True,capital_scale=scale,double_scale=ds,delay_scale=ls);row.update(family=family);folds.append(row)
                if run:
                    family_runs[family][year]=run['nominal'];double_runs[family][year]=run['double'];delay_runs[family][year]=run['delayed'];targets[family]=run['signals']
                    save_run(z,f'{family}/{year}',run['nominal']);z.writestr(f'{family}/{year}/signals.csv',run['signals'].to_csv(index_label='signal_bar_open'))
                else:errors.append(row)
                names={'A':['no_breadth','no_confirmation'],'B':['no_vol_ranking','lookback_30','lookback_90','lookback_180','lookback_365'],'C':['no_intraday_entry','no_daily_regime']}[family]
                for ab in names:
                    rr=ev.evaluate(m,cfg,year,scope='outer_oos_ablation',ablation=ab,capital_scale=scale,double_scale=ds,delay_scale=ls);rr['family']=family;ablations.append(rr)
            for name in baseline_runs:
                try:r=ev.replay(m,signals.baseline(m,name),year,details=True,capital_scale=capital(baseline_runs[name]));baseline_runs[name][year]=r;save_run(z,f'baseline_{name}/{year}',r)
                except ValueError as exc:errors.append(dict(name=name,year=year,reason=str(exc)))
            ensemble_members[year]=eligible_members
            if len(eligible_members)>=2 and all(f in targets for f in eligible_members):
                votes=pd.concat([targets[f].asset for f in eligible_members],axis=1)
                # Predeclared conservative unanimity: same concrete asset or CASH.
                asset=votes.iloc[:,0].where(votes.nunique(axis=1).eq(1),'CASH');tt=signals.admitted(m,asset)
                try:r=ev.replay(m,tt,year,details=True,capital_scale=capital(ensemble_runs));ensemble_runs[year]=r;save_run(z,f'E/{year}',r)
                except ValueError as exc:errors.append(dict(family='E',year=year,reason=str(exc)))
    summary=[]
    for family,runs in family_runs.items():
        if len(runs)!=4:summary.append(dict(family=family,status='REJECT_INCOMPLETE_EXECUTION_EVIDENCE',valid_folds=sorted(runs)));continue
        row,_=ev.stitch(runs);d,_=ev.stitch(double_runs[family]);late,_=ev.stitch(delay_runs[family]);row.update(family=family,status='VALID',double_cost_cagr=d['cagr'],double_cost_mdd=d['mdd'],delayed_cagr=late['cagr'],delayed_mdd=late['mdd']);row['baseline_qualifies']=baseline_pass(row);summary.append(row)
    for name,runs in baseline_runs.items():
        if len(runs)==4:r,_=ev.stitch(runs);summary.append(dict(family='baseline_'+name,status='VALID',**r))
    summary.append(dict(family='D',status='NOT_RUN_DATA_GATE',reason='Actual funding captured, but matched perpetual trade/mark and historical maintenance/liquidation evidence incomplete'))
    summary.append(dict(family='E',status='NOT_RUN_NO_QUALIFIED_MEMBERS' if not ensemble_runs else 'PARTIAL_PRIOR_OOS_ELIGIBLE',members_by_year=ensemble_members))
    write(OUT/'family_results.json',summary);write(OUT/'oos_folds.json',folds);write(OUT/'ablations.json',ablations);write(OUT/'execution_rejections.json',errors)
    # Freeze verification includes code, universe evidence and raw-data hash.
    for name,h in freeze['hashes'].items():assert digest(HERE/name)==h,name
    assert protected()==before,'Protected production tree changed'
    write(OUT/'receipt.json',dict(status='completed',seconds=time.time()-started,unique_search_evaluations=len(alltrials),generations=len(generation_log),neighbor_evaluations=len(neighbor_rows),ablation_evaluations=len(ablations),outer_fold_evaluations=len(folds),api_calls=designer_.calls,protected_files=len(before),protected_tree_unchanged=True,frozen_inputs_and_code_verified=True,forward_opened=False,production_writes=False,verdict='REJECT',reason='Validated-winner claim requires prospective sealed evidence and main numeric gates; no risk layers promoted'))
    print('Completed:',json.dumps(summary,default=str),flush=True)

if __name__=='__main__':main()
