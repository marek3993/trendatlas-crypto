"""Nested chronological selection with immutable, version-bound checkpoints."""
from __future__ import annotations
import argparse
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import random
import sqlite3
import time
import uuid

from .contract import load, validate
from .market import SPACE, canonical, digest, load_market, mutate, validate_genes
from .engine import evaluate, suite, eligibility, curve_metrics
from .compact import compact_parent

C=load()
CONTRACT={'api_calls_per_cycle_max':C['evolution']['api_calls_cycle_max'],
          'api_tokens_per_cycle_max':C['evolution']['api_tokens_cycle_max'],
          'api_usd_per_cycle_max':C['evolution']['api_usd_upper_cycle_max']}
MARKET=None
STRESSES=('nominal','double_cost','delayed_entry')

def utc():return datetime.now(timezone.utc).isoformat()

def atomic(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_name(path.name+'.'+str(os.getpid())+'.tmp')
    with temp.open('w') as f:f.write(canonical(value));f.flush();os.fsync(f.fileno())
    os.replace(temp,path)

def connect(root):
    root=Path(root);root.mkdir(parents=True,exist_ok=True)
    db=sqlite3.connect(root/'v2.sqlite',timeout=30)
    db.execute('PRAGMA journal_mode=WAL');db.execute('PRAGMA synchronous=FULL');db.execute('PRAGMA foreign_keys=ON')
    db.executescript('''
    CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS candidates(id TEXT PRIMARY KEY,genes TEXT NOT NULL,parent TEXT,
      source TEXT NOT NULL,origin INTEGER NOT NULL,generation INTEGER NOT NULL,created TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS evaluations(key TEXT PRIMARY KEY,candidate_id TEXT NOT NULL,origin INTEGER NOT NULL,
      stress TEXT NOT NULL,result TEXT NOT NULL,finished TEXT NOT NULL,UNIQUE(candidate_id,origin,stress));
    CREATE TABLE IF NOT EXISTS members(origin INTEGER,generation INTEGER,id TEXT,role TEXT NOT NULL,
      PRIMARY KEY(origin,generation,id));
    CREATE TABLE IF NOT EXISTS stages(origin INTEGER,generation INTEGER,state TEXT NOT NULL,request_hash TEXT,
      front_hash TEXT NOT NULL,PRIMARY KEY(origin,generation));
    CREATE TABLE IF NOT EXISTS selections(origin INTEGER PRIMARY KEY,candidate_id TEXT NOT NULL,genes TEXT NOT NULL,
      evidence TEXT NOT NULL,frozen_utc TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS test_books(origin INTEGER PRIMARY KEY,result TEXT NOT NULL,finished TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY,utc TEXT,kind TEXT,body TEXT,previous_hash TEXT,row_hash TEXT UNIQUE);
    CREATE TRIGGER IF NOT EXISTS evaluation_no_update BEFORE UPDATE ON evaluations BEGIN SELECT RAISE(ABORT,'immutable_v2_evaluation');END;
    CREATE TRIGGER IF NOT EXISTS evaluation_no_delete BEFORE DELETE ON evaluations BEGIN SELECT RAISE(ABORT,'immutable_v2_evaluation');END;
    CREATE TRIGGER IF NOT EXISTS candidate_no_update BEFORE UPDATE ON candidates BEGIN SELECT RAISE(ABORT,'immutable_v2_candidate');END;
    CREATE TRIGGER IF NOT EXISTS candidate_no_delete BEFORE DELETE ON candidates BEGIN SELECT RAISE(ABORT,'immutable_v2_candidate');END;
    CREATE TRIGGER IF NOT EXISTS selection_no_update BEFORE UPDATE ON selections BEGIN SELECT RAISE(ABORT,'immutable_v2_selection');END;
    CREATE TRIGGER IF NOT EXISTS selection_no_delete BEFORE DELETE ON selections BEGIN SELECT RAISE(ABORT,'immutable_v2_selection');END;
    CREATE TRIGGER IF NOT EXISTS book_no_update BEFORE UPDATE ON test_books BEGIN SELECT RAISE(ABORT,'immutable_v2_book');END;
    CREATE TRIGGER IF NOT EXISTS book_no_delete BEFORE DELETE ON test_books BEGIN SELECT RAISE(ABORT,'immutable_v2_book');END;
    CREATE TRIGGER IF NOT EXISTS event_no_update BEFORE UPDATE ON events BEGIN SELECT RAISE(ABORT,'append_only_v2_audit');END;
    CREATE TRIGGER IF NOT EXISTS event_no_delete BEFORE DELETE ON events BEGIN SELECT RAISE(ABORT,'append_only_v2_audit');END;
    ''')
    return db

def event(db,kind,**body):
    previous=db.execute('SELECT row_hash FROM events ORDER BY id DESC LIMIT 1').fetchone()
    prior=previous[0] if previous else 'GENESIS';stamp=utc();body=canonical(body)
    db.execute('INSERT INTO events(utc,kind,body,previous_hash,row_hash) VALUES(?,?,?,?,?)',
        (stamp,kind,body,prior,digest([stamp,kind,body,prior])))

def binding(inputs):
    here=Path(__file__).resolve().parent
    code=hashlib.sha256(b''.join((here/n).read_bytes() for n in ('engine.py','market.py','runtime.py','contract.py'))).hexdigest()
    contract=digest(C);manifest=json.loads((Path(inputs)/'manifest.json').read_text())
    for name,expected in manifest['files'].items():
        if hashlib.sha256((Path(inputs)/name).read_bytes()).hexdigest()!=expected:raise RuntimeError('input_binding:'+name)
    return {'engine':code,'contract':contract,'inputs':digest(manifest)}

def initialize(db,bindings):
    existing=db.execute("SELECT value FROM meta WHERE key='binding'").fetchone()
    if existing:
        if json.loads(existing[0])!=bindings:raise RuntimeError('v2_checkpoint_binding_changed')
        return
    cycle='phase2_v2_'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'_'+uuid.uuid4().hex[:8]
    with db:
        db.execute("INSERT INTO meta VALUES('binding',?)",(canonical(bindings),))
        db.execute("INSERT INTO meta VALUES('cycle',?)",(canonical(cycle),))
        event(db,'cycle_created',cycle=cycle,bindings=bindings,legacy_comparable=False)

def training_folds(origin):
    start=datetime.fromisoformat(C['walk_forward']['validation_folds'][origin][0]).date()
    end=start-timedelta(days=1);lo=start-timedelta(days=C['walk_forward']['train_days'])
    mid=lo+timedelta(days=(end-lo).days//2)
    return [[lo.isoformat(),mid.isoformat()],[(mid+timedelta(days=1)).isoformat(),end.isoformat()]]

def register(db,genes,parent,source,origin,generation):
    validate_genes(genes);cid=digest(genes)
    with db:
        cur=db.execute('INSERT OR IGNORE INTO candidates VALUES(?,?,?,?,?,?,?)',(cid,canonical(genes),parent,source,origin,generation,utc()))
        if cur.rowcount:event(db,'candidate_registered',id=cid,parent=parent,source=source,origin=origin,generation=generation)
        db.execute('INSERT OR IGNORE INTO members VALUES(?,?,?,?)',(origin,generation,cid,'mutation' if parent else 'initial'))
    return cid

def summary(db,cid,origin):
    row=db.execute('SELECT genes,parent,source FROM candidates WHERE id=?',(cid,)).fetchone()
    results={s:json.loads(r) for s,r in db.execute('SELECT stress,result FROM evaluations WHERE candidate_id=? AND origin=?',(cid,origin))}
    if len(results)!=3:return None
    if any('failure' in r for r in results.values()):
        failures=[r['failure'] for r in results.values() if 'failure' in r]
        return dict(id=cid,genes=json.loads(row[0]),parent=row[1],source=row[2],
            metrics={'cagr':None,'mdd':None,'sharpe':None,'calmar':None,'turnover':None},
            folds=[],eligible=False,reasons=['invalid_market_or_book'],failures=failures)
    nominal=results['nominal'];m=dict(nominal['metrics'])
    m.update(double_cost_cagr=results['double_cost']['metrics']['cagr'],delayed_entry_cagr=results['delayed_entry']['metrics']['cagr'])
    valid,reasons=eligibility(m)
    return dict(id=cid,genes=json.loads(row[0]),parent=row[1],source=row[2],metrics=m,
        folds=nominal['folds'],eligible=valid,reasons=reasons)

def pareto(rows):
    valid=[r for r in rows if r['eligible']]
    def vector(r):
        m=r['metrics'];return [m['cagr'],m['calmar'] if m['calmar'] is not None else -1e9,
            m['sharpe'] if m['sharpe'] is not None else -1e9,-m['mdd'],-m['turnover']]
    out=[]
    for r in valid:
        v=vector(r)
        if not any(all(a>=b for a,b in zip(vector(s),v)) and any(a>b for a,b in zip(vector(s),v)) for s in valid if s['id']!=r['id']):out.append(r)
    return sorted(out,key=lambda r:(-r['metrics']['cagr'],r['id']))

def survivors(rows):
    front=pareto(rows)
    rows=[r for r in rows if r['metrics']['cagr'] is not None]
    pool=front or sorted(rows,key=lambda r:(len(r['reasons']),r['metrics']['mdd'],-r['metrics']['cagr'],r['id']))
    return pool[:C['evolution']['survivors']],bool(front)

def seed(db,origin):
    if db.execute('SELECT 1 FROM members WHERE origin=? AND generation=0',(origin,)).fetchone():return
    if origin:
        # Previous origin's immutable genes and lineage survive; evaluation uses new past-only train window.
        gen=db.execute('SELECT MAX(generation) FROM stages WHERE origin=?',(origin-1,)).fetchone()[0]
        ids=[r[0] for r in db.execute('SELECT id FROM members WHERE origin=? AND generation=?',(origin-1,gen))]
        rows=[summary(db,cid,origin-1) for cid in ids];keep,_=survivors([r for r in rows if r])
        with db:
            for r in keep:db.execute('INSERT OR IGNORE INTO members VALUES(?,?,?,?)',(origin,0,r['id'],'inherited_survivor'))
            event(db,'origin_survivors_inherited',origin=origin,ids=[r['id'] for r in keep])
    for family,fields in SPACE.items():
        genes={'family':family,**{k:v[len(v)//2] for k,v in fields.items()}}
        register(db,genes,None,'predeclared_control',origin,0)
    # Fixed, explicitly previously selected legacy hypothesis; never labeled prospective independent.
    legacy={'family':'K','asset_weight_cap':.25,'correlation_cap':.7,'rebalance_days':28,'trend_days':180,'vol_days':20,'vol_target':.24}
    register(db,legacy,None,'legacy_selected_hypothesis',origin,0)

def init_worker(m):
    global MARKET;MARKET=m

def job(task):
    cid,genes,origin,stress=task
    try:
        r=evaluate(MARKET,genes,training_folds(origin),cost_mult=2 if stress=='double_cost' else 1,delay_entries=stress=='delayed_entry')
    except ValueError as e:
        r={'failure':{'type':'ValueError','reason':str(e)},'eligible':False,'training':training_folds(origin)}
    return cid,origin,stress,r

def pending(db,origin,generation,bindings):
    tasks=[]
    for cid,genes in db.execute('SELECT c.id,c.genes FROM candidates c JOIN members m ON m.id=c.id WHERE m.origin=? AND m.generation=? ORDER BY c.id',(origin,generation)):
        for stress in STRESSES:
            if not db.execute('SELECT 1 FROM evaluations WHERE candidate_id=? AND origin=? AND stress=?',(cid,origin,stress)).fetchone():tasks.append((cid,json.loads(genes),origin,stress))
    return tasks

def store_job(db,bindings,outcome):
    cid,origin,stress,r=outcome
    key=digest([bindings,cid,origin,stress,training_folds(origin)])
    with db:
        db.execute('INSERT INTO evaluations VALUES(?,?,?,?,?,?)',(key,cid,origin,stress,canonical(r),utc()))
        event(db,'evaluation_complete',key=key,id=cid,origin=origin,stress=stress)

def proposal(db,origin,generation,parents,all_rows,cycle):
    family=parents[0]['genes']['family']
    parents=[p for p in parents if p['genes']['family']==family][:2]
    seen={r[0] for r in db.execute('SELECT id FROM candidates')};options=[]
    for k in range(12):
        p=parents[k%len(parents)];genes,_=mutate(p['genes'],int(digest([cycle,origin,generation,k])[:8],16),seen)
        if genes is not None:seen.add(digest(genes));options.append({'parent':p['id'],'genes':genes})
    cutoff=training_folds(origin)[-1][1]
    return dict(cycle_id=cycle,generation=generation,family=family,parents=[compact_parent(p) for p in parents],
        aggregate={'evaluated':len(all_rows),'eligible':sum(r['eligible'] for r in all_rows),'pareto_size':len(pareto(all_rows)),
            'rejection_counts':dict(Counter(reason for r in all_rows for reason in r['reasons'])),'training_cutoff':cutoff,
            'selection_scope':'past_only_nested_inner_validation','test_start':C['walk_forward']['validation_folds'][origin][0]},
        unseen_options=options,schema=SPACE[family],scope='development_inner_validation_only')

def advance(db,root,origin,generation):
    ids=[r[0] for r in db.execute('SELECT id FROM members WHERE origin=? AND generation=?',(origin,generation))]
    rows=[summary(db,cid,origin) for cid in ids]
    if any(r is None for r in rows):return 'EVALUATING'
    keep,valid=survivors(rows);front_hash=digest([r['id'] for r in pareto(rows)])
    stage=db.execute('SELECT state,request_hash,front_hash FROM stages WHERE origin=? AND generation=?',(origin,generation)).fetchone()
    if stage and stage[0]=='ADVANCED':return 'ADVANCED'
    if stage and stage[0]=='FROZEN':return 'FROZEN'
    prior=[r[0] for r in db.execute('SELECT front_hash FROM stages WHERE origin=? AND generation<? ORDER BY generation DESC LIMIT ?',
        (origin,generation,C['evolution']['stop_front_stagnant_generations']))]
    stop=generation>=C['evolution']['max_generations'] or (len(prior)>=C['evolution']['stop_front_stagnant_generations'] and all(h==front_hash for h in prior))
    if stop:
        # No invalid trial gets promoted merely because the valid front is empty.
        chosen=keep[0] if valid else {'id':'CASH','genes':'CASH'}
        with db:
            db.execute('INSERT OR IGNORE INTO selections VALUES(?,?,?,?,?)',(origin,chosen['id'],canonical(chosen['genes']),
                canonical({'training':training_folds(origin),'eligible_front_size':len(pareto(rows)),
                    'selection':'valid_training_pareto' if valid else 'CASH_EMPTY_VALID_FRONT','candidate_ids':ids}),utc()))
            db.execute('INSERT OR REPLACE INTO stages VALUES(?,?,?,?,?)',(origin,generation,'FROZEN',None,front_hash))
            event(db,'selection_frozen_before_test',origin=origin,id=chosen['id'],training_cutoff=training_folds(origin)[-1][1])
        return 'FROZEN'
    if not stage:
        if not keep:
            with db:
                db.execute('INSERT OR IGNORE INTO selections VALUES(?,?,?,?,?)',(origin,'CASH',canonical('CASH'),
                    canonical({'training':training_folds(origin),'selection':'CASH_ALL_TRIALS_INVALID'}),utc()))
                db.execute('INSERT INTO stages VALUES(?,?,?,?,?)',(origin,generation,'FROZEN',None,front_hash))
                event(db,'selection_frozen_before_test',origin=origin,id='CASH',training_cutoff=training_folds(origin)[-1][1])
            return 'FROZEN'
        # Select a family from training evidence; never send current/future test results.
        payload=proposal(db,origin,generation,keep,rows,json.loads(db.execute("SELECT value FROM meta WHERE key='cycle'").fetchone()[0]))
        key=digest(payload);atomic(Path(root)/'mailbox/requests'/(key+'.json'),{'hash':key,'payload':payload})
        with db:db.execute('INSERT INTO stages VALUES(?,?,?,?,?)',(origin,generation,'WAITING',key,front_hash))
        return 'WAITING'
    response_path=Path(root)/'mailbox/responses'/(stage[1]+'.json')
    if not response_path.exists():return 'WAITING'
    response=json.loads(response_path.read_text());request=json.loads((Path(root)/'mailbox/requests'/(stage[1]+'.json')).read_text())['payload']
    if response['hash']!=stage[1]:raise RuntimeError('proposal_binding')
    seen={r[0] for r in db.execute('SELECT id FROM candidates')};parent_map={r['id']:r for r in rows}
    accepted=[];reject=[]
    if response['state']=='COMPLETE':
        try:
            body=json.loads(response['content'])
            if set(body)!= {'candidates'} or not isinstance(body['candidates'],list) or len(body['candidates'])!=4:raise ValueError('envelope')
            for child in body['candidates']:
                if set(child)!={'parent','genes','hypothesis'} or not isinstance(child['hypothesis'],str) or len(child['hypothesis'])>600:raise ValueError('mutation_shape')
                validate_genes(child['genes'])
                if child['parent'] not in {p['id'] for p in request['parents']} or child['genes']['family']!=request['family']:raise ValueError('parent_or_family')
                cid=digest(child['genes'])
                if cid in seen:reject.append({'id':cid,'reason':'duplicate'});continue
                seen.add(cid);accepted.append(child)
        except (ValueError,TypeError,KeyError) as e:reject.append({'reason':str(e)});accepted=[]
    with db:
        for p in keep:db.execute('INSERT OR IGNORE INTO members VALUES(?,?,?,?)',(origin,generation+1,p['id'],'survivor'))
    for child in accepted:register(db,child['genes'],child['parent'],'deepseek:'+child['hypothesis'],origin,generation+1)
    # Match the real DeepSeek arm's parent and family. Invalid or absent API does not get credited as AI.
    parents=[parent_map[p['id']] for p in request['parents']]
    for k in range(C['evolution']['mutations_per_arm_per_generation']):
        p=parents[k%len(parents)];genes,why=mutate(p['genes'],int(digest([origin,generation,'det',k])[:8],16),seen)
        if genes is not None:
            seen.add(digest(genes));register(db,genes,p['id'],why,origin,generation+1)
    with db:
        db.execute('UPDATE stages SET state=? WHERE origin=? AND generation=?',('ADVANCED',origin,generation))
        event(db,'generation_advanced',origin=origin,generation=generation,parents=[p['id'] for p in keep],
            deepseek_accepted=len(accepted),rejected=reject,request=stage[1],usage=response.get('usage'))
    return 'ADVANCED'

def test_selected(db,origin,m):
    if db.execute('SELECT 1 FROM test_books WHERE origin=?',(origin,)).fetchone():return
    selection=db.execute('SELECT genes,evidence,frozen_utc FROM selections WHERE origin=?',(origin,)).fetchone()
    if selection is None:raise RuntimeError('test_before_selection_freeze')
    prev=db.execute('SELECT result FROM test_books WHERE origin=?',(origin-1,)).fetchone()
    state=json.loads(prev[0])['checkpoint'] if prev else None
    f=[C['walk_forward']['validation_folds'][origin]]
    result=evaluate(m,json.loads(selection[0]),f,initial_state=state)
    with db:
        db.execute('INSERT INTO test_books VALUES(?,?,?)',(origin,canonical(result),utc()))
        event(db,'development_test_complete',origin=origin,selection_frozen_utc=selection[2],
            last_nav=result['equity'][-1]['equity'])

def quality(db,origin):
    groups={}
    for cid,source,parent in db.execute('SELECT id,source,parent FROM candidates WHERE origin<=?',(origin,)):
        r=summary(db,cid,origin)
        if r is None or r['metrics']['cagr'] is None:continue
        arm='deepseek' if source.startswith('deepseek:') else 'deterministic' if source.startswith('deterministic:') else 'control'
        p=summary(db,parent,origin) if parent else None
        bucket=groups.setdefault(arm,{'evaluated':0,'eligible':0,'cagr_sum':0.,'parent_delta_sum':0.,'paired':0})
        bucket['evaluated']+=1;bucket['eligible']+=r['eligible'];bucket['cagr_sum']+=r['metrics']['cagr']
        if p and p['metrics']['cagr'] is not None:bucket['parent_delta_sum']+=r['metrics']['cagr']-p['metrics']['cagr'];bucket['paired']+=1
    for b in groups.values():
        b['mean_cagr']=b.pop('cagr_sum')/b['evaluated'];b['mean_parent_delta']=b.pop('parent_delta_sum')/b['paired'] if b['paired'] else None
    return {'origin':origin,'training_only':True,'arms':groups,'advantage_proven':False,'comparison':'same-origin same-parent; counts differ when API invalid/budgeted; descriptive, not independent statistical proof'}

def status(db):
    current=db.execute('SELECT origin,generation,state FROM stages ORDER BY origin DESC,generation DESC LIMIT 1').fetchone()
    last=db.execute('SELECT MAX(finished),COUNT(*) FROM evaluations').fetchone()
    done=db.execute('SELECT COUNT(*) FROM test_books').fetchone()[0]
    return dict(active_evolution=done<len(C['walk_forward']['validation_folds']),
        cycle=json.loads(db.execute("SELECT value FROM meta WHERE key='cycle'").fetchone()[0]),
        stage=current,evaluations=last[1],last_progress_utc=last[0],test_folds_completed=done,
        outer_oos='LOCKED',forward_2027='SEALED',historical_outer='NONE_PREVIOUSLY_SEEN')

def references(m,inputs,out):
    import csv
    from .inputs import guarded_rows
    targets={}
    with (Path(inputs)/'production_targets.csv').open('rb') as f:
        for row in guarded_rows(f,C):targets[row['date']]=(row['execution_target_asset'],float(row['execution_target_exposure']))
    rules={'PRODUCTION':'PRODUCTION','BTC_BUY_HOLD':'BTC_BUY_HOLD','BTC_SMA200':'BTC_SMA200',
        'OLD_BEST':{'family':'K','asset_weight_cap':.25,'correlation_cap':.7,'rebalance_days':28,'trend_days':180,'vol_days':20,'vol_target':.24},
        'CASH':'CASH','BTC_HALF':'BTC_HALF','BTC_SMA100':'BTC_SMA100'}
    results={};out=Path(out);out.mkdir(parents=True,exist_ok=True)
    for name,rule in rules.items():
        try:r=suite(m,rule,C['walk_forward']['validation_folds'],production_targets=targets)
        except ValueError as exc:
            r={'metrics':{'cagr':None,'mdd':None,'no_top3_trades_cagr':None},
                'state':'UNDEFINED_INVALID','failure':str(exc),'scope':'full_requested_development',
                'no_imputed_price':True,'no_invented_liquidation':True}
            if name in ('PRODUCTION','BTC_BUY_HOLD','BTC_SMA200'):raise
        atomic(out/(name+'.json'),r);results[name]=r['metrics']
        print(canonical({'reference':name,'metrics':r['metrics']}),flush=True)
    atomic(out/'summary.json',{'scope':'previously_seen_development_not_independent_OOS','metrics':results,
        'same_engine':True,'same_timing':True,'same_costs':True,'outer_read':False,'forward_read':False,
        'invalid_references':[name for name,m in results.items() if m['cagr'] is None]})
    return results

def run(root,inputs,workers=2,seconds=240,steps=None):
    validate(C,activate=True)
    root=Path(root);root.mkdir(parents=True,exist_ok=True)
    import fcntl
    with (root/'runner.lock').open('a+') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        db=connect(root)
        try:
            bindings=binding(inputs);initialize(db,bindings)
            if not (root/'references/summary.json').exists():raise RuntimeError('references_must_complete_before_evolution')
            market=load_market(Path(inputs));init_worker(market)
            deadline=time.monotonic()+seconds;count=0
            with ProcessPoolExecutor(max_workers=workers,initializer=init_worker,initargs=(market,)) as pool:
                while time.monotonic()<deadline and (steps is None or count<steps):
                    count+=1;done=db.execute('SELECT COUNT(*) FROM test_books').fetchone()[0]
                    if done>=len(C['walk_forward']['validation_folds']):break
                    origin=done;seed(db,origin)
                    gen=db.execute('SELECT MAX(generation) FROM members WHERE origin=?',(origin,)).fetchone()[0]
                    tasks=pending(db,origin,gen,bindings)
                    if tasks:
                        # Bounded worker batches are transactionally checkpointed per complete evaluation.
                        for result in pool.map(job,tasks[:workers]):store_job(db,bindings,result)
                        atomic(root/'status.json',status(db));continue
                    state=advance(db,root,origin,gen)
                    atomic(root/'quality.json',quality(db,origin))
                    if state=='FROZEN':test_selected(db,origin,market)
                    atomic(root/'status.json',status(db))
                    if state=='WAITING':break
            return status(db)
        finally:db.close()

def main():
    p=argparse.ArgumentParser();p.add_argument('command',choices=['run','references','status'])
    p.add_argument('--root',type=Path,required=True);p.add_argument('--inputs',type=Path);p.add_argument('--workers',type=int,choices=[1,2],default=2)
    p.add_argument('--seconds',type=int,default=240);p.add_argument('--steps',type=int)
    a=p.parse_args()
    if a.command=='references':
        validate(C,activate=True);bindings=binding(a.inputs);m=load_market(a.inputs)
        references(m,a.inputs,a.root/'references');db=connect(a.root);initialize(db,bindings);atomic(a.root/'status.json',status(db));db.close()
    elif a.command=='run':print(canonical(run(a.root,a.inputs,a.workers,a.seconds,a.steps)))
    else:
        db=sqlite3.connect('file:'+str(a.root/'v2.sqlite')+'?mode=ro',uri=True);print(canonical(status(db)));db.close()

if __name__=='__main__':main()
