"""Predeclared development -> nominee freeze -> validation -> finalist freeze -> OOS.

No results flow backwards. --replay-proposals reproduces without paid API calls.
"""
import argparse,io,json,time,zipfile
from pathlib import Path
import numpy as np
import pandas as pd
from common import HERE,SPEC,config,cid,digest,write,log,now,neighbors
from data import load
from signals import targets,panel,initial
from ledger import replay
from evaluate import survivors,qualified,slots,gate,fronts
from designer import Designer

class Experiment:
    def __init__(self,out,proposals=None,continue_proposals=False):
        self.out=out;out.mkdir(parents=True,exist_ok=True)
        self.designer=Designer(proposals,continue_proposals);self.results={};self.targets={};self.markets={};self.rows=[];self.counter=0;self.saved=set()
    def market(self,track,scope):
        end=SPEC['periods'][scope][1];key=(track,end)
        if key not in self.markets:self.markets[key]=load(track,end)
        return self.markets[key]
    def evaluate(self,c,scope,track=None,capital=100.,stress='nominal',detail=False,overlay='none'):
        track=track or ('perp' if c and c['family']=='D' else 'spot');identity=cid(c) if c else 'BTC_SMA200_'+track
        key=(identity,scope,capital,stress,overlay)
        if key in self.results:return self.results[key]
        m=self.market(track,scope);tk=(identity,scope)
        if tk not in self.targets:self.targets[tk]=targets(m,c or config(),benchmark=c is None)
        kw={'double_cost':dict(cost_mult=2.),'delay':dict(delay=1),'coarse':dict(coarse=True),'margin10':dict(mm=.1,mark_extra=.01),'margin20':dict(mm=.2,mark_extra=.03),'funding_adverse':dict(fund_adverse=True,mm=.2,mark_extra=.03)}.get(stress,{})
        start,end=SPEC['periods'][scope];r=replay(m,self.targets[tk],start,end,capital=capital,details=detail,overlay=overlay,gross_limit=c['gross'] if c and c['family']=='D' else 1.0,**kw)
        row=dict(candidate_id=identity,candidate=c,family=c['family'] if c else 'BENCHMARK',track=track,certification='CONSERVATIVE_PROXY' if track=='perp' else 'SPOT_RESEARCH_PROXY',scope=scope,capital=capital,stress=stress,overlay=overlay,**r['metrics'])
        self.counter+=1;row['evaluation_index']=self.counter;self.results[key]=(row,r);self.rows.append(row)
        log(self.out/'progress.jsonl',dict(utc=now(),**row));print(self.counter,scope,identity,stress,capital,'reliable',row['reliable'],flush=True)
        return row,r
    def save_run(self,z,row,r):
        stem=f"{row['candidate_id']}/{row['capital']:g}/{row['stress']}/{row['overlay']}"
        if stem in self.saved:return
        self.saved.add(stem)
        z.writestr(stem+'/daily.csv',r['daily'].to_csv(float_format='%.12g'))
        for k in ['metrics','folds','episodes','orders','fills','assets','episode_logs']:z.writestr(stem+'/'+k+'.json',json.dumps(r[k],allow_nan=False,default=str))
        if r['bars'] is not None:
            z.writestr(stem+'/bars.csv',r['bars'].to_csv(float_format='%.12g'));z.writestr(stem+'/quantities.csv',pd.DataFrame(r['quantities'],index=r['bars'].index,columns=r['assets']).to_csv(float_format='%.12g'))
    def run(self):
        if (self.out/'development.json').exists():raise ValueError('Refuse overwriting previous experiment evidence')
        freeze=json.loads((HERE/'engine_freeze.json').read_text())
        for name,h in freeze['files'].items():assert digest(HERE/name)==h,'Frozen engine changed: '+name
        fixed=panel();development={};evolution={};gens=[]
        bench_dev={t:self.evaluate(None,'development',t)[0] for t in ['spot','perp']}
        # Both arms finish ALL development and API calls before validation is loaded.
        for family in ['F','G','H','D']:
            for arm in ['deterministic','deepseek']:
                population=[];seen=set();candidates=initial(family)
                for generation in range(4):
                    for c in candidates:
                        row,_=self.evaluate(c,'development');development[cid(c)]=row;population.append(row);seen.add(cid(c))
                    population=survivors(population);gens.append(dict(family=family,arm=arm,generation=generation,survivors=[r['candidate_id'] for r in population],seen=sorted(seen)))
                    if generation<3:
                        candidates=self.designer.propose(family,arm,population,[r['candidate'] for r in population],seen,SPEC['evolution']['seed']+100*ord(family)+generation)
                        log(self.out/'designer_events.jsonl',self.designer.events[-1])
                evolution[family+'_'+arm]=population
        for c in fixed:
            row,_=self.evaluate(c,'development');development[cid(c)]=row
        write(self.out/'development.json',list(development.values()));write(self.out/'generations.json',gens)
        write(self.out/'deepseek_summary.json',dict(calls=self.designer.calls,estimated_usd=self.designer.cost,reserved_upper_usd=self.designer.reserved,tokens=sum(e.get('billing',{}).get('total_tokens',0) for e in self.designer.events),accepted=sum(len(e['accepted']) for e in self.designer.events),rejected=sum(len(e['rejected']) for e in self.designer.events),events_sha256=digest(self.out/'designer_events.jsonl')))
        nominees={cid(c):c for c in fixed}
        for population in evolution.values():nominees.update({r['candidate_id']:r['candidate'] for r in population})
        write(self.out/'validation_nominees_frozen.json',dict(utc=now(),candidates=nominees,development_sha256=digest(self.out/'development.json'),events_sha256=digest(self.out/'designer_events.jsonl')))
        bench_val={t:self.evaluate(None,'validation',t)[0] for t in ['spot','perp']};validation={}
        for identity,c in nominees.items():
            r,_=self.evaluate(c,'validation');r['qualified']=qualified(r,development[identity],bench_val[r['track']]);r['benchmark']=gate(r,bench_val[r['track']]);validation[identity]=r
        finalists={}
        for family in ['F','G','H','D']:
            for arm in ['deterministic','deepseek']:
                allowed={r['candidate_id'] for r in evolution[family+'_'+arm]}|{cid(c) for c in fixed if c['family']==family}
                finalists[family+'_'+arm]={slot:dict(candidate=r['candidate'],candidate_id=r['candidate_id'],qualified=r['qualified'],validation_cagr=r['cagr'],validation_mdd=r['mdd']) for slot,r in slots([validation[i] for i in allowed]).items()}
        unique={v['candidate_id']:v['candidate'] for s in finalists.values() for v in s.values()}
        qualified_ids=[i for i in unique if validation[i]['qualified']]
        overlays={i:SPEC['overlays']['panel'] for i in qualified_ids if unique[i]['family']!='D'}
        # Overlay panel eligibility is fixed from baseline development+validation, not OOS.
        for identity,ovs in overlays.items():
            for overlay in ovs[1:]:
                self.evaluate(unique[identity],'development',overlay=overlay);self.evaluate(unique[identity],'validation',overlay=overlay)
        write(self.out/'validation.json',list(validation.values()))
        write(self.out/'finalists_frozen.json',dict(utc=now(),finalists=finalists,unique=unique,overlays=overlays,neighbors={i:neighbors(c) for i,c in unique.items()},validation_sha256=digest(self.out/'validation.json'),forward_opened=False,rule='Validation slots frozen; rejected slots remain diagnostics. No OOS reselection.'))
        outer={};folds=[];stresses=[];neighbor_rows=[];capacity=[];ablation=[]
        with zipfile.ZipFile(self.out/'ledgers.zip','w',zipfile.ZIP_DEFLATED) as z:
            benchmarks={}
            for t in ['spot','perp']:
                r,run=self.evaluate(None,'oos',t,detail=True);benchmarks[t]=r;self.save_run(z,r,run);outer[r['candidate_id']]=r;folds.extend(dict(candidate_id=r['candidate_id'],track=t,**f) for f in run['folds'])
                for stress in ['double_cost','delay','coarse']:
                    a,b=self.evaluate(None,'oos',t,stress=stress,detail=True);self.save_run(z,a,b);stresses.append(a)
            for c in unique.values():self.evaluate(c,'oos',detail=True)
            for c in list({cid(c):c for c in fixed+list(unique.values())}.values()):
                i=cid(c);row,run=self.evaluate(c,'oos',detail=i in unique);row['benchmark']=gate(row,benchmarks[row['track']],True);row['validation_qualified']=validation[i]['qualified']
                self.save_run(z,row,run);outer[i]=row;folds.extend(dict(candidate_id=i,track=row['track'],**f) for f in run['folds'])
                if i not in unique:continue
                for stress in ['double_cost','delay','coarse']+(['margin10','margin20','funding_adverse'] if c['family']=='D' else []):
                    a,b=self.evaluate(c,'oos',stress=stress,detail=True);self.save_run(z,a,b);stresses.append(a)
                for cap in SPEC['execution']['accounts_usd'][1:]:
                    a,b=self.evaluate(c,'oos',capital=float(cap));capacity.append(a);self.save_run(z,a,b)
                for nc in neighbors(c):
                    # No mutation selection, forward feedback or test-driven reranking.
                    nr,nrun=self.evaluate(nc,'oos');neighbor_rows.append(dict(parent=i,**nr));self.save_run(z,nr,nrun)
                for overlay in overlays.get(i,[])[1:]:
                    a,b=self.evaluate(c,'oos',overlay=overlay,detail=True);self.save_run(z,a,b);ablation.append(a)
            for t in ['spot','perp']:
                for cap in SPEC['execution']['accounts_usd'][1:]:
                    a,b=self.evaluate(None,'oos',t,capital=float(cap));capacity.append(a);self.save_run(z,a,b)
        write(self.out/'oos.json',list(outer.values()));write(self.out/'folds.json',folds);write(self.out/'stress.json',stresses);write(self.out/'neighbors.json',neighbor_rows);write(self.out/'capacity.json',capacity);write(self.out/'overlay_ablations.json',ablation)
        # Finalist-only PASS evaluation. Descriptive panel front cannot replace frozen slots.
        decisions={}
        for i,c in unique.items():
            r=outer[i];sr=[s for s in stresses if s['candidate_id']==i];ns=[s for s in neighbor_rows if s['parent']==i]
            checks=dict(validation=r['validation_qualified'],reliable=r['reliable'],benchmark=r['benchmark']['passed'],target=r['cagr']>=1.5 and r['mdd']<=.35 and r['sharpe']>=1.5 and r['calmar']>=4,folds=r['profitable_folds']>=2,stresses=all(s['reliable'] and s['cagr']>0 and s['mdd']<=.35 for s in sr),no_best_day=r['no_best_day_cagr']>0 and r['no_best_day_mdd']<=.35,no_top3=r['no_top3_cagr']>0 and r['no_top3_mdd']<=.35,neighbors=sum(n['reliable'] and n['cagr']>0 and n['mdd']<=.35 for n in ns)/max(1,len(ns))>=.75)
            decisions[i]=dict(decision='PASS' if all(checks.values()) else 'REJECT',checks=checks)
        write(self.out/'decision.json',dict(utc=now(),overall='PASS' if any(d['decision']=='PASS' for d in decisions.values()) else 'REJECT',candidates=decisions,forward_opened=False,venue_certified=False))
        write(self.out/'all_evaluations.json',self.rows)
        for name,rows in [('all_evaluations',self.rows),('common_table',list(outer.values())),('annual_folds',folds),('stresses',stresses),('neighbors',neighbor_rows),('capacity',capacity)]:pd.DataFrame(rows).to_csv(self.out/(name+'.csv'),index=False)
        pareto=[dict(r,pareto_track=t) for t in ['spot','perp'] for r in fronts([r for r in outer.values() if r['track']==t and r['reliable']])[0]]
        write(self.out/'pareto_front.json',pareto);pd.DataFrame(pareto).to_csv(self.out/'pareto_front.csv',index=False)
        write(self.out/'completed.json',dict(utc=now(),evaluations=self.counter,engine_sha256=digest(HERE/'engine_freeze.json'),finalists_sha256=digest(self.out/'finalists_frozen.json')))
        print('COMPLETE',self.counter,flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output-dir',type=Path,default=HERE/'results');p.add_argument('--replay-proposals',type=Path);p.add_argument('--continue-proposals',type=Path);args=p.parse_args()
    path=args.replay_proposals or args.continue_proposals
    recorded=[json.loads(line) for line in path.read_text().splitlines()] if path else None
    Experiment(args.output_dir,recorded,bool(args.continue_proposals)).run()
