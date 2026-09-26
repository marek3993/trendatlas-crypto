"""Frozen development evolution -> finalist freeze -> chronological outer replay.

No production imports, account interfaces, legacy returns, or OOS feedback into
the proposer. Run from this directory with `python run.py` after data_finalize.
"""
import argparse,datetime,json,time,zipfile
from pathlib import Path
import numpy as np
import pandas as pd
import designer,evaluate as ev,ledger,market,signals,perpetual_gate
from common import HERE,PARENT,SPEC,cid,digest,write,log

ENGINE=['common.py','market.py','identity.py','identity_events.json','venue_notices.json','signals.py','ledger.py','designer.py','evaluate.py','run.py','contract.json','test_followup.py','perpetual_gate.py']

def freeze():
    path=HERE/'engine_data_freeze.json'
    hashes={f:digest(HERE/f) for f in ENGINE+[p.name for p in HERE.glob('*.zip')]}
    hashes['../new_strategy_20260926/ledger.py']=digest(PARENT/'ledger.py')
    hashes['../new_strategy_20260926/contract.json']=digest(PARENT/'contract.json')
    if path.exists():assert json.loads(path.read_text())['hashes']==hashes,'Frozen evaluator/data changed'
    else:write(path,dict(utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),hashes=hashes,before_current_attempt_performance=True,before_any_real_performance=not (HERE/'attempts').exists(),prior_attempts_archived=(HERE/'attempts').exists(),before_any_API_or_outer=True,protocol_sha256=digest(HERE/'protocol_freeze.json'),source_commit=SPEC['source_commit']))

def clean(x):
    if isinstance(x,dict):return {k:clean(v) for k,v in x.items()}
    if isinstance(x,list):return [clean(v) for v in x]
    if isinstance(x,np.generic):return x.item()
    return x

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output-dir',type=Path,default=HERE/'results');parser.add_argument('--replay-proposals',type=Path);args=parser.parse_args()
    begin=time.time();out=args.output_dir;out.mkdir(parents=True,exist_ok=True)
    if (out/'development.json').exists():raise RuntimeError('Do not overwrite results; archive a failed attempt explicitly before rerun')
    freeze();perpetual_gate.main();m=market.load();recorded=[json.loads(s) for s in args.replay_proposals.read_text().splitlines()] if args.replay_proposals else None;d=designer.Designer(replay=recorded);dev=[];generations=[];chosen={};benchdev={};neighbor_rows=[]
    # No outer rows are computed until all development calls and freezes end.
    for origin in SPEC['evolution']['origins']:
        year=origin-1;benchdev[year]=ev.evaluate(m,None,year,stress=True)[0]
        for arm in SPEC['evolution']['arms']:
            rows=[];seen=set();population=designer.initial();lookup={}
            for generation in range(4):
                for cfg in population:
                    key=cid(cfg)
                    if key in seen:continue
                    r,_,_=ev.evaluate(m,cfg,year,benchdev[year]);r.update(arm=arm,origin=origin,generation=generation,proposal_source='seed' if generation==0 else next(x['source'] for x in d.events[-1]['accepted_final'] if cid(x['candidate'])==key))
                    rows.append(r);dev.append(r);seen.add(key);lookup[key]=r
                    log(out/'development_progress.jsonl',clean(r))
                current=[lookup[cid(c)] for c in population];survive=ev.survivors(current)
                generations.append(dict(origin=origin,arm=arm,generation=generation,population=[cid(c) for c in population],survivors=[r['candidate_id'] for r in survive],pareto=[r['candidate_id'] for r in ev.fronts(current)[0]]))
                print('development',origin,arm,'generation',generation+1,'evaluated',len(rows),'feasible',sum(ev.feasible(r) for r in rows),flush=True)
                if generation<3:
                    mutations=d.propose(arm,rows,[r['candidate'] for r in survive],seen,SPEC['evolution']['seed']+origin*10+generation)
                    log(out/'designer_events.jsonl',clean(d.events[-1]));population=[r['candidate'] for r in survive]+mutations
            assert len(rows)==22
            chosen[arm,origin]=ev.champion(rows)
    assert len(dev)==SPEC['evolution']['max_search_evaluations']
    write(out/'development.json',clean(dev));write(out/'generations.json',generations)
    write(out/'deepseek_summary.json',dict(calls=d.calls,estimated_usd=d.estimated_usd,reserved_upper_usd=d.reserved_usd,successful_responses=sum('usage' in e for e in d.events),accepted_proposals=sum(len(e['accepted_proposals']) for e in d.events),rejected_proposals=sum(len(e['rejected_proposals']) for e in d.events),input_scope='Development whitelist only; all API calls precede outer evaluation',key_available=designer.api_key()[0] is not None,total_tokens=sum(e.get('billing',{}).get('total_tokens',0) for e in d.events),events_file='designer_events.jsonl',price_is_estimate_not_invoice=True))
    finalists={}
    for arm in SPEC['evolution']['arms']:
        rows=[r for r in dev if r['origin']==2026 and r['arm']==arm];valid=[r for r in rows if r['status']=='VALID'];front=ev.fronts(valid)[0] if valid else []
        feasible=[r for r in front if ev.feasible(r)]
        finalists[arm]=dict(robust=chosen[arm,2026],aggressive=max(front,key=lambda r:(r['cagr'],r['candidate_id'])) if front else None,compromise=max(feasible,key=lambda r:(r['calmar'],r['candidate_id'])) if feasible else None)
    write(out/'finalists_frozen.json',clean(dict(utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),prospective_evaluation_opened=False,outer_evaluation_started=False,finalists=finalists,walk_forward_champions={arm:{str(y):chosen[arm,y] for y in SPEC['evolution']['origins']} for arm in SPEC['evolution']['arms']},pareto_2025={arm:[r['candidate_id'] for r in ev.fronts([r for r in dev if r['origin']==2026 and r['arm']==arm])[0]] for arm in SPEC['evolution']['arms']})))
    parents={(arm,origin,parent['candidate_id']):parent for (arm,origin),parent in chosen.items()}
    for arm,slots in finalists.items():
        for parent in slots.values():
            if parent is not None:parents[arm,2026,parent['candidate_id']]=parent
    for (arm,origin,_),parent in parents.items():
        for cfg in designer.neighbors(parent['candidate']):
            row,_,_=ev.evaluate(m,cfg,origin-1,benchdev[origin-1],stress=False);row.update(arm=arm,origin=origin,parent_id=parent['candidate_id']);neighbor_rows.append(row)
        print('neighbor stress',origin,arm,flush=True)
    write(out/'neighbors.json',clean(neighbor_rows))
    outer=[];aggregate=[]
    with zipfile.ZipFile(out/'replay_ledgers.zip','w',zipfile.ZIP_DEFLATED) as detail:
        def store(label,capital,year,stage,run):
            prefix=f'{label}/{capital}/{year}/{stage}/'
            detail.writestr(prefix+'bars.csv',run['daily'].to_csv(float_format='%.12g'))
            for key in ['orders','fills','episodes']:detail.writestr(prefix+key+'.json',json.dumps(clean(run[key]),allow_nan=False,default=str))
            detail.writestr(prefix+'terminal.json',json.dumps(clean({k:v for k,v in run.items() if k not in ['daily','orders','fills','episodes']}),default=str))
        def series(label,configs,capital,stress=True):
            combined={};failures=[]
            for stage,cost,lag in [('nominal',1.,2)]+([('double',2.,2),('delayed',1.,3)] if stress else []):
                amount=float(capital);runs={};chain_broken=False
                for year in SPEC['stress']['folds']:
                    cfg=configs[year];target=signals.benchmark(m) if cfg is None else signals.target(m,cfg)
                    meta=dict(label=label,initial_capital=capital,capital_start=amount,year=year,stage=stage,candidate_id='BTC_SMA200' if cfg is None else cid(cfg),candidate=cfg,scope='outer_oos',capital_basis='independent initial-capital diagnostic after failed compounding chain' if chain_broken else 'chronological compounded NAV')
                    try:
                        run=ev.replay(m,target,year,capital=amount,mult=cost,lag=lag,details=True);summary=ledger.summarize(run);row=dict(meta,status='VALID',**summary);runs[year]=run;amount=run['ending_nav'];store(label,capital,year,stage,run)
                    except ledger.UnsafeExecution as exc:
                        row=dict(meta,status='UNSAFE_EXECUTION',reason=str(exc));failures.append(row)
                        if exc.partial:store(label,capital,year,stage+'_partial',exc.partial)
                        outer.append(row);log(out/'outer_progress.jsonl',clean(row));chain_broken=True;amount=float(capital);continue
                    outer.append(row);log(out/'outer_progress.jsonl',clean(row))
                    if chain_broken:amount=float(capital)
                if len(runs)==4:
                    summary,run=ev.stitch(runs);combined[stage]=summary
                    detail.writestr(f'{label}/{capital}/{stage}_equity.csv',run['daily'][['equity','nav_usd','cash_usd']].to_csv(float_format='%.12g'))
            row=dict(label=label,capital=capital,nominal=combined.get('nominal'),double=combined.get('double'),delayed=combined.get('delayed'),status='VALID' if len(combined)==(3 if stress else 1) else 'UNSAFE_EXECUTION',failures=failures,stress_tested=stress)
            aggregate.append(row);write(out/'aggregate_partial.json',clean(aggregate));print('outer',label,capital,row['status'],flush=True)
        for capital in SPEC['accounts_usd']:series('BTC_SMA200',{y:None for y in SPEC['stress']['folds']},capital)
        for arm in SPEC['evolution']['arms']:
            for capital in SPEC['accounts_usd']:series('B_'+arm,{y:chosen[arm,y]['candidate'] for y in SPEC['stress']['folds']},capital)
        for cfg in designer.panel():
            for capital in SPEC['accounts_usd']:series('panel_'+cid(cfg),{y:cfg for y in SPEC['stress']['folds']},capital,stress=capital==100)
    write(out/'outer_folds.json',clean(outer));write(out/'aggregate.json',clean(aggregate));write(out/'run_completed.json',dict(seconds=time.time()-begin,completed_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),development_evaluations=len(dev),neighbor_evaluations=len(neighbor_rows),outer_fold_replays=len(outer),api_calls=d.calls,engine_freeze_sha256=digest(HERE/'engine_data_freeze.json'),finalists_freeze_sha256=digest(out/'finalists_frozen.json'),family_C='ARCHIVED_REJECT',family_D='NOT_RUN_INCOMPLETE_VENUE_CONTRACT',family_E='NOT_RUN_NO_TWO_QUALIFIED_FAMILIES'))
    print('COMPLETED',round(time.time()-begin,1),'seconds',flush=True)

if __name__=='__main__':main()
