"""Bounded nested search -> immutable nominations -> terminal outer estimation."""
import json
import random
from collections import defaultdict
import numpy as np
from .protocol import CONTRACT, periods, initial, four_mutations, plateau_neighbors, complexity, digest, atomic, utc
from .vendor.common import cid, config, canonical
from .evaluator import Evaluator, log_returns, prefix_audit
from .statistics import survivors, pareto_front, paired_bootstrap, dsr, holm, cscv, metrics as log_metrics

class AwaitBroker(Exception):pass

def benchmark_gate(m,b):
    gain=(m['cagr']>=b['cagr']+.05 or m['mdd']<=b['mdd']-.05 or m['sharpe']>=b['sharpe']+.15 or m['calmar']>=b['calmar']+.25 or
          (m['asset_concentration'] is not None and b['asset_concentration'] is not None and m['asset_concentration']<=b['asset_concentration']-.15))
    no_loss=(m['cagr']>=b['cagr']-.10 and m['mdd']<=b['mdd']+.05 and m['sharpe']>=b['sharpe']-.20 and m['calmar']>=b['calmar']-.30)
    return bool(gain and no_loss)

def score_candidate(evaluator,genes,origin,track):
    folds=[];bn=[];ns=plateau_neighbors(genes);neighbor_quality=[]
    for p in periods(origin):
        if p['scope']=='outer':continue
        r=evaluator.evaluate(genes,p,track);b=evaluator.evaluate(config(),p,track,benchmark=True)
        folds.append(dict(p,metrics=r['metrics']));bn.append(b['metrics'])
        for n in ns:
            # Neighbors are counted hypotheses even when cache avoids duplicate arithmetic.
            st=evaluator.store
            st.add_trial(f'neighbor:{origin}:{track}:{cid(n)}',f'{origin}:{track}:neighbors',0,n,cid(genes),'plateau','Frozen lexical adjacent-enum plateau probe')
            nr=evaluator.evaluate(n,p,track)['metrics']
            if p['scope']=='inner_validation':neighbor_quality.append(nr['reliable'] and nr['cagr']>0 and nr['mdd']<=.35)
    ms=[f['metrics'] for f in folds];val=[f['metrics'] for f in folds if f['scope']=='inner_validation']
    result=dict(id=cid(genes),genes=genes,folds=folds,complexity=complexity(genes),
                mean_inner_cagr=float(np.mean([m['cagr'] for m in ms])),
                median_sharpe=float(np.median([m['sharpe'] for m in ms])),
                median_calmar=float(np.median([m['calmar'] for m in ms])),
                maximum_mdd=max(m['mdd'] for m in ms),worst_validation_fold=min(m['cagr'] for m in val),
                profitable_fold_fraction=float(np.mean([m['cagr']>0 for m in ms])),
                plateau_fraction=float(np.mean(neighbor_quality)) if neighbor_quality else 0.,seed_consistency=0.,
                turnover=float(np.mean([m['turnover'] for m in ms])),cost_fraction=float(np.mean([m['costs_usd']/100 for m in ms])),
                asset_concentration=max(m['asset_concentration'] if m['asset_concentration'] is not None else 1. for m in ms),
                episode_concentration=max(m['episode_concentration'] if m['episode_concentration'] is not None else 1. for m in ms),
                benchmark_delta=float(np.mean([m['cagr']-b['cagr'] for m,b in zip(ms,bn)])),
                reliable=all(m['reliable'] for m in ms),
                benchmark_pass=all(benchmark_gate(m,b) for m,b in zip(ms,bn)),
                validation_cagr=float(np.mean([m['cagr'] for m in val])),validation_mdd=max(m['mdd'] for m in val),
                validation_calmar=float(np.median([m['calmar'] for m in val])))
    return result

def vector(row):
    if not row['reliable']:return [-1e6]*14
    values=[row[k] for k in CONTRACT['pareto']['maximize']]+[-row[k] for k in CONTRACT['pareto']['minimize']]
    # Fixed epsilon boxes: nearly equivalent financial outcomes prefer simplicity.
    eps=[.01,.02,.05,.01,.01,.01,.01,.01,.005,.1,.005,.01,.01,1.]
    return [round(v/e)*e for v,e in zip(values,eps)]

def proposals(store,run,generation,selected,seen,seed,inline_broker,synthetic):
    # The worker never imports networking code. Broker queue is a JSON mailbox.
    from .proposal_schema import make_payload
    p=make_payload(run,generation,selected,seen);pid=digest(p)
    row=store.mail.execute('SELECT * FROM proposals WHERE id=?',(pid,)).fetchone()
    if row is None:
        with store.mail:store.mail.execute('INSERT INTO proposals(id,run,generation,payload,state,created) VALUES(?,?,?,?,?,?)',
                                       (pid,run,generation,canonical(p),'QUEUED',utc()))
    if inline_broker:
        from .designer import broker_once
        broker_once(store.mailbox,forced_no_key=synthetic)
    row=store.mail.execute('SELECT * FROM proposals WHERE id=?',(pid,)).fetchone()
    if row['state'] in ('QUEUED','INFLIGHT'):
        store.set('pause_reason','WAITING_FOR_DEVELOPMENT_ONLY_BROKER');store.status();raise AwaitBroker()
    validation=json.loads(row['validation']);accepted=validation['accepted']
    fallback=four_mutations([r['genes'] for r in selected],seed,set(seen)|{cid(x['genes']) for x in accepted})
    result=[dict(x,source='deepseek') for x in accepted]
    result += [dict(x,source='deterministic_fallback') for x in fallback[:4-len(result)]]
    return result

def nominations(rows):
    viable=[r for r in rows if r['reliable']]
    if not viable:viable=rows
    front=[viable[i] for i in pareto_front(viable)]
    qualified=[r for r in front if r['worst_validation_fold']>0 and r['maximum_mdd']<=.35 and r['benchmark_pass'] and r['plateau_fraction']>=.75]
    pool=qualified or front
    robust=[r for r in pool if r['validation_mdd']<=.25] or pool
    return dict(A=max(pool,key=lambda r:(r['validation_cagr'],-r['complexity'],r['id'])),
                B=min(robust,key=lambda r:(r['validation_mdd'],-r['validation_calmar'],r['complexity'],r['id'])),
                C=max(pool,key=lambda r:(r['validation_calmar'],-r['complexity'],r['id'])))

def run_search(store,evaluator,synthetic=False,inline_broker=False):
    if store.meta('search_frozen',False):return
    budget=CONTRACT['budget'];origins=[2024] if synthetic else budget['outer_origins'];maxgen=2 if synthetic else budget['max_generations']
    # Complete all generations/seeds of all origins BEFORE evaluating any outer fold.
    for origin in origins:
        for island in (['F_spot'] if synthetic else budget['islands']):
            family,track=island.split('_')
            for generation in range(maxgen):
                groups={}
                for arm in budget['arms']:
                    for seed in budget['seeds']:
                        run=f'{origin}:{island}:{seed}:{arm}';done=store.meta('done:'+run,False)
                        if done:continue
                        store.set('run',run);store.set('generation',generation);store.status()
                        pop=store.population(run,generation)
                        if pop is None:
                            if generation:raise RuntimeError('Missing predecessor population')
                            pop=[dict(genes=c,parent=None,source='seed',hypothesis='Frozen initial hypothesis, previously seen history') for c in initial(family,seed)]
                            store.population(run,generation,pop)
                        rows=[]
                        for entry in pop:
                            c=entry['genes'];i=cid(c)
                            # Every newly proposed budget slot counted once, cached clones remain slots.
                            store.add_trial(f'{run}:{generation}:{i}',run,generation,c,entry['parent'],entry['source'],entry['hypothesis'])
                            saved=store.db.execute('SELECT body FROM scores WHERE run=? AND generation=? AND candidate=?',(run,generation,i)).fetchone()
                            row=json.loads(saved[0]) if saved else score_candidate(evaluator,c,origin,track)
                            if not saved:
                                with store.db:store.db.execute('INSERT INTO scores VALUES(?,?,?,?)',(run,generation,i,canonical(row)))
                            rows.append(row)
                        groups[(arm,seed)]=(run,rows)
                # Island/arm consistency across independently evolving seeds is a separate Pareto axis.
                for (arm,seed),(run,rows) in groups.items():
                    seed_values=[max(r['worst_validation_fold'] for r in rs) for (ar,_),(_,rs) in groups.items() if ar==arm]
                    if len(seed_values)<3:
                        for other in budget['seeds']:
                            prior=store.meta(f'last_seed_quality:{origin}:{island}:{other}:{arm}')
                            if prior is not None and (arm,other) not in groups:seed_values.append(prior)
                    consistency=sum(v>0 for v in seed_values)/3
                    store.set(f'last_seed_quality:{run}',max(r['worst_validation_fold'] for r in rows))
                    for row in rows:row['seed_consistency']=consistency;row['vector']=vector(row)
                    selected=survivors(rows,6)
                    front=sorted(r['id'] for r in (rows[i] for i in pareto_front(rows)))
                    historical=store.meta('front_vectors:'+run,[])
                    fresh=[r['vector'] for r in rows]
                    improved=not historical or any(not any(all(a>=b for a,b in zip(old,v)) for old in historical) for v in fresh)
                    flat=0 if improved else store.meta('flat:'+run,0)+1
                    # Metadata commits are idempotent when resuming mid-generation.
                    stage=store.meta(f'processed:{run}:{generation}',False)
                    if not stage:
                        store.set('front:'+run,front);store.set('flat:'+run,flat)
                        union=[dict(vector=v) for v in historical+fresh]
                        store.set('front_vectors:'+run,[union[i]['vector'] for i in pareto_front(union)])
                        store.set(f'processed:{run}:{generation}',True)
                        store.set(f'selection:{run}:{generation}',selected)
                    else:selected=store.meta(f'selection:{run}:{generation}');flat=store.meta('flat:'+run,0)
                    best=max(rows,key=lambda r:r['validation_calmar'])
                    store.set('best_development',dict(run=run,id=best['id'],validation_cagr=best['validation_cagr'],validation_mdd=best['validation_mdd'],validation_calmar=best['validation_calmar'],selection='display_only_not_weighted_fitness'))
                    stop=(generation==maxgen-1 or len({r['id'] for r in selected})<6 or flat>=3)
                    if stop:
                        for slot,row in nominations(selected).items():
                            frozen=dict(row,origin=origin,island=island,seed=seed,arm=arm,slot=slot,
                                        neighbors=plateau_neighbors(row['genes']),selected_only_from_inner=True)
                            with store.db:store.db.execute('INSERT OR IGNORE INTO finalists VALUES(?,?,?)',(run,slot,canonical(frozen)))
                        store.set('done:'+run,True);store.set('stop_reason:'+run,'max_generations' if generation==maxgen-1 else 'no_diversity' if len({r['id'] for r in selected})<6 else 'no_pareto_improvement_3_generations')
                        continue
                    if store.population(run,generation+1) is not None:continue
                    seen={r[0] for r in store.db.execute('SELECT candidate FROM trials WHERE run=?',(run,))}
                    mutation_seed=seed+origin*100+generation*31
                    if arm=='deepseek':mut=proposals(store,run,generation+1,selected,seen,mutation_seed,inline_broker,synthetic)
                    else:mut=[dict(m,source='deterministic') for m in four_mutations([r['genes'] for r in selected],mutation_seed,seen)]
                    newpop=[dict(genes=r['genes'],parent=r['id'],source='survivor',hypothesis='Pareto survivor, no new hypothesis') for r in selected]+mut
                    store.population(run,generation+1,newpop);store.export_lineage();store.status()
    # Separate freeze barrier persists before any outer request. A crash never reopens search.
    store.set('search_frozen',True);store.set('phase','FROZEN');store.set('prospective_status','FROZEN_NOT_YET_OBSERVED')
    atomic(store.root/'frozen_finalists.json',[json.loads(r[0]) for r in store.db.execute('SELECT body FROM finalists ORDER BY run,slot')])
    store.export_lineage();store.status()

def combined(values):
    """Independent annual books compounded for the frozen adaptive selection rule.

    Each fold starts at $100; no invented liquidation/transfer between folds.
    This is walk-forward estimation, not a continuous executable account curve.
    """
    lr=np.concatenate([log_returns(v) for v in values]);ms=[v['metrics'] for v in values];out=log_metrics(lr)
    curve=np.exp(np.cumsum(lr));dd=float(np.max(1-curve/np.maximum.accumulate(np.r_[1,curve])[1:]))
    out.update(mdd=max(dd,max(m['mdd'] for m in ms)),trades=sum(m['trades'] for m in ms),
               reliable=all(m['reliable'] for m in ms),asset_concentration=max(m['asset_concentration'] if m['asset_concentration'] is not None else 1. for m in ms),
               episode_concentration=max(m['episode_concentration'] if m['episode_concentration'] is not None else 1. for m in ms),
               turnover=float(np.mean([m['turnover'] for m in ms])),costs_usd=sum(m['costs_usd'] for m in ms),
               fee_usd=sum(m['fee_usd'] for m in ms),slippage_usd=sum(m['slippage_usd'] for m in ms),funding_debit_usd=sum(m['funding_debit_usd'] for m in ms),funding_credit_usd=sum(m['funding_credit_usd'] for m in ms),
               worst_fold=min(f['cagr'] for v in values for f in v['folds']),profitable_folds=sum(f['cagr']>0 for v in values for f in v['folds']),
               median_holding_days=float(np.median([e['holding_days'] for v in values for e in v['episodes'] if e['closed']])) if any(m['trades'] for m in ms) else 0.,
               exposure=float(np.mean([m['exposure'] for m in ms])),net_exposure=float(np.mean([m['net_exposure'] for m in ms])),gross_drift_abs_mean=float(np.mean([m['gross_drift_abs_mean'] for m in ms])),gross_drift_abs_max=max(m['gross_drift_abs_max'] for m in ms),max_actual_gross=max(m['max_actual_gross'] for m in ms),residual_usd=sum(m['residual_usd'] for m in ms),
               flags=sorted(set(f for m in ms for f in m['flags'])))
    out['calmar']=out['cagr']/out['mdd'] if out['mdd'] else 0.
    return out,lr

def remove_concentration(values):
    lr=np.concatenate([log_returns(v) for v in values]);nb=lr.copy();nb[np.argmax(nb)]=0
    episodes=[max(0,e['log_growth']) for v in values for e in v['episodes'] if e['closed']]
    # Exact complete episode account log attribution, including fees/funding.
    return dict(no_best_day_cagr=log_metrics(nb)['cagr'],
                no_top3_cagr=float(np.expm1((lr.sum()-sum(sorted(episodes,reverse=True)[:3]))/(len(lr)/365.25))))

def development_cscv(store,island):
    # Use only evaluated development books and common hypotheses across origins.
    grouped=defaultdict(dict)
    for row in store.db.execute('SELECT cache_key,request FROM evaluations'):
        request=json.loads(row['request']);p=request['period']
        if p['scope']!='inner_validation' or request['track']!=island.split('_')[1] or request['genes']['family']!=island[0] or request['benchmark'] or request['cash']:continue
        value=store.cached(row['cache_key']);grouped[cid(request['genes'])][p['start']]=log_returns(value)
    all_periods=sorted(set(d for x in grouped.values() for d in x))
    columns=[np.concatenate([v[d] for d in all_periods]) for v in grouped.values() if set(v)==set(all_periods)]
    return cscv(np.array(columns).T if columns else np.zeros((0,0)))

def outer_estimate(store,evaluator,synthetic=False):
    if store.meta('status')=='SEALED':return
    if not store.meta('search_frozen',False):raise RuntimeError('Unfrozen finalists')
    atomic(store.root/'mailbox'/'SEALED.json',dict(reason='All search frozen; no further proposals',utc=utc()))
    store.set('outer_opened',True);store.set('phase','OUTER_TERMINAL');store.status()
    all_final=[json.loads(r[0]) for r in store.db.execute('SELECT body FROM finalists ORDER BY run,slot')]
    groups=defaultdict(list)
    for f in all_final:groups[(f['island'],f['seed'],f['arm'],f['slot'])].append(f)
    diagnostics={island:development_cscv(store,island) for island in CONTRACT['budget']['islands']}
    rows=[];fold_rows=[];audit_rows=[];equities=[];regimes=[];benchmark_seen=set();trial_sharpes=[json.loads(r[0])['median_sharpe'] for r in store.db.execute('SELECT body FROM scores')]
    trials=store.db.execute("SELECT COUNT(*) FROM trials WHERE source!='survivor'").fetchone()[0]
    trials+=store.db.execute("SELECT COUNT(*) FROM attempts WHERE status!='COMPLETE'").fetchone()[0]+store.meta('prior_attempts',0)
    for key,finalists in groups.items():
        island,seed,arm,slot=key;track=island.split('_')[1];books=[];benchmarks=[];stress_books=defaultdict(list);neighbor_books=defaultdict(list);capacity_books=defaultdict(list)
        for f in sorted(finalists,key=lambda x:x['origin']):
            period=[p for p in periods(f['origin']) if p['scope']=='outer'][0]
            store.set('run',f"OUTER:{f['origin']}:{island}:{seed}:{arm}:{slot}");store.status()
            for stress in ('nominal','double_cost','later_bar','adverse_mark_fill','coarse_lot','no_holding_cap')+(('maintenance10','maintenance20') if track=='perp' else ()):
                v=evaluator.evaluate(f['genes'],period,track,stress,details=stress=='nominal');stress_books[stress].append(v)
                fold_rows.append(dict(island=island,seed=seed,arm=arm,slot=slot,candidate=f['id'],year=f['origin'],stress=stress,capital=100,**v['metrics']))
                if stress=='nominal':books.append(v);capacity_books[100].append(v)
            for capital in (1000,10000,100000):
                v=evaluator.evaluate(f['genes'],period,track,capital=capital)
                bc=evaluator.evaluate(config(),period,track,capital=capital,benchmark=True);capacity_books[capital].append(v)
                fold_rows.append(dict(island=island,seed=seed,arm=arm,slot=slot,candidate=f['id'],year=f['origin'],stress='capacity',capital=capital,benchmark_cagr=bc['metrics']['cagr'],benchmark_mdd=bc['metrics']['mdd'],**v['metrics']))
            for j,n in enumerate(f['neighbors']):neighbor_books[j].append(evaluator.evaluate(n,period,track))
            b=evaluator.evaluate(config(),period,track,benchmark=True);benchmarks.append(b)
            if (track,f['origin']) not in benchmark_seen:
                benchmark_seen.add((track,f['origin']))
                for day in b['daily']:equities.append(dict(island='BTC_'+track,seed=0,arm='benchmark',slot='C',candidate='BTC_SMA200',**day))
            evaluator.evaluate(config(),period,track,cash=True)
            audit=prefix_audit(f['genes'],track,evaluator.model(track,period['end']),f"{f['origin']}-07-01",period=period,reference=books[-1])
            audit_rows.append(audit)
            for day in books[-1]['daily']:
                equities.append(dict(island=island,seed=seed,arm=arm,slot=slot,candidate=f['id'],**day))
            # Regime diagnosis uses a BTC observation already public before the
            # entire UTC day begins. It is attribution, never a filtered PnL path.
            market=evaluator.model(track,period['end']);btc=market['close']['BTCUSDT']
            labels=(btc>btc.rolling(200).mean()).shift(2,fill_value=False)
            daylogs=log_returns(books[-1])
            for positive in (False,True):
                ids=[j for j,d in enumerate(books[-1]['daily']) if bool(labels.loc[d['date']])==positive]
                regimes.append(dict(island=island,seed=seed,arm=arm,slot=slot,year=f['origin'],regime='BTC_positive' if positive else 'BTC_nonpositive',observed_days=len(ids),
                    log_growth_contribution=float(daylogs[ids].sum()),geometric_contribution=float(np.expm1(daylogs[ids].sum())),
                    fee_usd=sum(books[-1]['daily'][i]['fee'] for i in ids),slippage_usd=sum(books[-1]['daily'][i]['slippage'] for i in ids),
                    interpretation='Attribution of actual unchanged daily account, not an executable regime-filtered strategy'))
        if len(finalists)>1:
            # Actual continuous account across annual folds; switches frozen before outer.
            ordered=sorted(finalists,key=lambda x:x['origin']);schedule=[dict(year=f['origin'],genes=f['genes']) for f in ordered]
            whole=dict(scope='outer',fold='continuous_frozen_schedule',start=f"{ordered[0]['origin']}-01-01",end=f"{ordered[-1]['origin']}-12-31")
            for stress in list(stress_books):
                value=evaluator.evaluate(ordered[0]['genes'],whole,track,stress,schedule=schedule,details=stress=='nominal')
                stress_books[stress]=[value]
                for fold in value['folds']:fold_rows.append(dict(island=island,seed=seed,arm=arm,slot=slot,candidate='frozen_annual_schedule',stress=stress,capital=100,book='CONTINUOUS_PRIMARY',**fold))
            books=stress_books['nominal'];benchmarks=[evaluator.evaluate(config(),whole,track,benchmark=True)]
            for capital in (100,1000,10000,100000):
                value=evaluator.evaluate(ordered[0]['genes'],whole,track,capital=capital,schedule=schedule)
                bc=evaluator.evaluate(config(),whole,track,capital=capital,benchmark=True);capacity_books[capital]=[value]
                fold_rows.append(dict(island=island,seed=seed,arm=arm,slot=slot,candidate='frozen_annual_schedule',stress='capacity',capital=capital,book='CONTINUOUS_PRIMARY',benchmark_cagr=bc['metrics']['cagr'],benchmark_mdd=bc['metrics']['mdd'],**value['metrics']))
            for j in neighbor_books:
                ns=[dict(year=f['origin'],genes=f['neighbors'][j]) for f in ordered]
                neighbor_books[j]=[evaluator.evaluate(ns[0]['genes'],whole,track,schedule=ns)]
            equities=[d for d in equities if not (d['island']==island and d['seed']==seed and d['arm']==arm and d['slot']==slot)]
            for day in books[0]['daily']:equities.append(dict(island=island,seed=seed,arm=arm,slot=slot,candidate='frozen_annual_schedule',book='CONTINUOUS_PRIMARY',**day))
            if (track,'continuous') not in benchmark_seen:
                benchmark_seen.add((track,'continuous'));equities=[d for d in equities if d['island']!='BTC_'+track]
                for day in benchmarks[0]['daily']:equities.append(dict(island='BTC_'+track,seed=0,arm='benchmark',slot='C',candidate='BTC_SMA200',book='CONTINUOUS_PRIMARY',**day))
        m,lr=combined(books);b,br=combined(benchmarks);stresses={s:combined(v)[0] for s,v in stress_books.items()}
        m.update(remove_concentration(books));neigh=[combined(v)[0] for v in neighbor_books.values()]
        supported=[capital for capital,values in capacity_books.items() if all(v['metrics']['reliable'] for v in values)]
        m['maximum_supported_tested_account_usd']=max(supported) if supported else 0
        plateau=float(np.mean([n['reliable'] and n['cagr']>0 and n['mdd']<=.35 for n in neigh])) if neigh else 0.
        stat=paired_bootstrap(lr,br,m['trades'],replicates=49 if synthetic else None);deflated=dsr(lr,trials,trial_sharpes)
        row=dict(island=island,seed=seed,arm=arm,slot=slot,candidates=[f['id'] for f in finalists],
                 metrics=m,benchmark=b,benchmark_pass=benchmark_gate(m,b),stresses=stresses,neighbors=neigh,plateau_fraction=plateau,
                 bootstrap=stat,dsr=deflated,pbo=diagnostics[island],inner_reliable=all(f['reliable'] and f['worst_validation_fold']>0 and f['maximum_mdd']<=.35 for f in finalists),
                 independent_history=False,certification='CONSERVATIVE_PERP_PROXY' if track=='perp' else 'SPOT_RESEARCH_PROXY')
        rows.append(row)
        atomic(store.root/'outer_checkpoint.json',dict(rows=rows,folds=fold_rows,audits=audit_rows))
    adjusted=holm([r['bootstrap']['pvalue'] for r in rows])
    for r,adj in zip(rows,adjusted):
        r['bootstrap']['holm_pvalue']=adj;m=r['metrics'];reasons=[]
        seed_peers=[x for x in rows if (x['island'],x['arm'],x['slot'])==(r['island'],r['arm'],r['slot'])]
        seed_ok=len(seed_peers)==3 and all(x['metrics']['reliable'] and x['metrics']['cagr']>0 and x['metrics']['mdd']<=.35 for x in seed_peers)
        r['search_seed_stability']=dict(pass_gate=seed_ok,seeds=[dict(seed=x['seed'],cagr=x['metrics']['cagr'],mdd=x['metrics']['mdd']) for x in seed_peers])
        if not r['inner_reliable']:reasons.append('inner_fold_failure')
        if not m['reliable']:reasons.append('execution_reliability')
        if not r['benchmark_pass']:reasons.append('BTC_SMA200_noninferiority_or_gain')
        if m['mdd']>.35:reasons.append('MDD_above35')
        if m['asset_concentration']>.6:reasons.append('asset_concentration')
        if m['episode_concentration']>.35:reasons.append('episode_concentration')
        if m['no_top3_cagr']<-.05:reasons.append('no_top3_loss')
        if m['no_best_day_cagr']<=0:reasons.append('no_best_day_loss')
        if not all(v['reliable'] and v['cagr']>0 and v['mdd']<=.35 for v in r['stresses'].values()):reasons.append('execution_cost_or_margin_stress')
        if r['plateau_fraction']<.75:reasons.append('parameter_plateau')
        if not seed_ok:reasons.append('search_seed_instability')
        if r['bootstrap']['status']=='INCONCLUSIVE' or r['pbo']['status']=='INCONCLUSIVE':reasons.append('statistical_power_INCONCLUSIVE')
        if r['dsr']['probability']<.95:reasons.append('deflated_sharpe')
        if r['bootstrap']['excess_log_growth_ci'][0]<=0 or adj>.05:reasons.append('bootstrap_Holm_excess')
        if r['pbo']['pbo'] is None or r['pbo']['pbo']>.1:reasons.append('CSCV_PBO')
        if any(not a['pass_audit'] for a in audit_rows):reasons.append('causality_audit')
        r['rejection_reasons']=reasons;r['decision']='REJECT' if reasons else 'RESEARCH_PASS_REQUIRES_PROSPECTIVE'
        r['target_pass']=not reasons and m['cagr']>=1.5 and m['sharpe']>=1.5 and m['calmar']>=4
    valid=[r for r in rows if not r['rejection_reasons']]
    compact=lambda r:dict(island=r['island'],arm=r['arm'],seed=r['seed'],slot=r['slot'],candidates=r['candidates'],metrics=r['metrics']) if r else None
    high=[r for r in valid if r['target_pass']];robust=[r for r in valid if r['metrics']['mdd']<=.25]
    decision=dict(A=compact(max(high,key=lambda r:r['metrics']['calmar'])) if high else None,
                  B=compact(min(robust,key=lambda r:(r['metrics']['mdd'],-r['metrics']['calmar']))) if robust else None,
                  C=compact(max(valid,key=lambda r:r['metrics']['calmar'])) if valid else None,
                  D='REJECT' if not valid else 'RESEARCH_ONLY_NOT_PRODUCTION_APPROVAL',
                  E='FROZEN_FORWARD_CANDIDATES_AWAIT_CLOSED_PROSPECTIVE_DATA',history='PREVIOUSLY_SEEN_NOT_GLOBAL_SEALED')
    atomic(store.root/'results.json',rows);atomic(store.root/'folds.json',fold_rows);atomic(store.root/'regime_folds.json',regimes);atomic(store.root/'audit_results.json',audit_rows);atomic(store.root/'equity.json',equities)
    store.set('decision',decision);store.set('reject_reasons',sorted(set(x for r in rows for x in r['rejection_reasons'])))
    store.set('phase','TERMINAL');store.set('status','SEALED');store.set('next_refit',CONTRACT['continuation']['first_refit']);store.set('pause_reason',None)
    store.export_lineage();store.status()
