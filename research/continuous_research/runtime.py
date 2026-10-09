"""One bounded activation; the persisted planner outlives every finite batch."""
import gzip
import hashlib
import json
import shutil
import sqlite3
from pathlib import Path
from .common import canonical,digest,utc,period,atomic,atomic_bytes,lease,live_lease
from .contract import load
from .ledger import connect,meta,event,verify
from .planner import initialize,ingest,ensure_request,freeze_next,frequency_key,remaining
from .bootstrap import metrics


def binding(inputs,bootstrap):
    from research.discovery_evolution.runtime import source_binding
    here=Path(__file__).resolve().parent
    return {'contract':digest(load()),'code':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(here.glob('*.py'))},
            'bootstrap':hashlib.sha256(Path(bootstrap).read_bytes()).hexdigest(),
            'immutable_ancestor':source_binding(inputs,here.parents[1]/'bootstrap.json')}


def market(inputs):
    from research.phase2_v2.market import load_market
    from research.phase2_v2.inputs import guarded_rows
    from research.phase2_v2.contract import load as phase2
    from research.anomaly_lab.rules import prepare
    from research.discovery_evolution.runtime import restricted_market
    m=load_market(Path(inputs),load()['development'][1]);production={}
    with (Path(inputs)/'production_targets.csv').open('rb') as stream:
        for r in guarded_rows(stream,phase2()):production[r['date'][:10]]=(r['execution_target_asset'],float(r['execution_target_exposure']))
    f=prepare(m,production);return restricted_market(m,f),f


def default_evaluator(m,f,genes,interval,stress):
    from research.discovery_evolution.runtime import checked_evaluate
    return checked_evaluate(m,f,genes,interval,stress)


def inbox(db,root,m,f,batch,p,discovery_fn=None):
    key=frequency_key(p['rule']);row=db.execute('SELECT body FROM discoveries WHERE id=?',(key,)).fetchone()
    if row:d=json.loads(row[0])
    else:
        from research.discovery_evolution.discovery import discover
        lease(root,'DISCOVERY',batch=batch,rule=key)
        try:d={'valid':True,**(discovery_fn or discover)(m,f,p['rule'],[load()['training'][0],load()['feedback_cutoff']])}
        except (ValueError,KeyError,IndexError,FloatingPointError) as exc:
            d={'valid':False,'rule':p['rule'],'error_type':type(exc).__name__,'error':str(exc),'verdict':'UNDEFINED_INVALID','bounded_episodes':None}
        with db:
            db.execute('INSERT INTO discoveries VALUES(?,?,?,?)',(key,canonical(d),'continuous_scheduler',utc()))
            event(db,'discovery_computed',batch=batch,rule=key,result=digest(d),valid=d.get('valid',True))
    if not db.execute('SELECT 1 FROM inbox WHERE id=?',(p['id'],)).fetchone():
        body={'proposal':p['id'],'gene':p['gene_id'],'origin':p['origin'],'request':p['request'],'discovery':key,
              'discovery_hash':digest(d),'cutoff':load()['feedback_cutoff'],'orders_allowed':False}
        with db:
            db.execute('INSERT INTO inbox VALUES(?,?,?,?)',(p['id'],batch,canonical(body),utc()))
            event(db,'discovery_to_inbox',batch=batch,**body)
    body=json.loads(db.execute('SELECT body FROM inbox WHERE id=?',(p['id'],)).fetchone()[0]);atomic(Path(root)/'inbox'/f"{p['id']}.json",body)
    if not db.execute('SELECT 1 FROM candidates WHERE id=?',(p['gene_id'],)).fetchone():
        with db:
            db.execute('INSERT INTO candidates VALUES(?,?,?,?,?)',(p['gene_id'],p['id'],batch,canonical(p),utc()))
            event(db,'inbox_consumed',batch=batch,candidate=p['gene_id'],proposal=p['id'],origin=p['origin'],request=p['request'])
    return d


def backtest(db,root,m,f,gid,genes,phase,interval,stress='nominal',evaluator=default_evaluator):
    key=digest([gid,phase,interval,stress]);row=db.execute('SELECT body FROM backtests WHERE key=?',(key,)).fetchone()
    if row:return json.loads(row[0])
    row=db.execute('SELECT id FROM attempts WHERE key=?',(key,)).fetchone()
    if row:aid=row[0]
    else:
        with db:
            cur=db.execute('INSERT INTO attempts(key,candidate,phase,utc) VALUES(?,?,?,?)',(key,gid,phase,utc()));aid=cur.lastrowid
            event(db,'backtest_reserved',attempt=aid,key=key,candidate=gid,phase=phase)
    lease(root,'BACKTEST',candidate=gid,phase_name=phase,attempt=aid)
    try:
        result=evaluator(m,f,genes,interval,stress)
        stored={'metrics':result['metrics'],'equity':result['equity'],'audit':result['audit']}
        raw=gzip.compress(canonical(stored).encode(),mtime=0);name=f'books/{key}.json.gz';path=Path(root)/name
        if path.exists() and path.read_bytes()!=raw:raise RuntimeError('non_deterministic_checkpoint')
        if not path.exists():atomic_bytes(path,raw)
        body={'valid':True,'attempt':aid,'metrics':result['metrics'],'audit':result['audit'],
              'book':name,'book_sha256':hashlib.sha256(raw).hexdigest()}
    except (ValueError,KeyError,IndexError,AssertionError,FloatingPointError,ZeroDivisionError) as exc:
        body={'valid':False,'attempt':aid,'metrics':None,'error_type':type(exc).__name__,'error':str(exc),'verdict':'UNDEFINED_INVALID'}
    with db:
        db.execute('INSERT INTO backtests VALUES(?,?,?,?,?)',(key,gid,phase,canonical(body),utc()))
        event(db,'backtest_completed',attempt=aid,key=key,candidate=gid,phase=phase,valid=body['valid'])
    return body


def book(root,receipt):
    raw=(Path(root)/receipt['book']).read_bytes()
    if hashlib.sha256(raw).hexdigest()!=receipt['book_sha256']:raise ValueError('book_integrity')
    return json.loads(gzip.decompress(raw))


def evaluate_candidate(db,root,m,f,batch,p,discovery,evaluator=default_evaluator,now=None):
    c=load();gid=p['gene_id'];row=db.execute('SELECT id FROM scientific_attempts WHERE candidate=?',(gid,)).fetchone()
    if row:index=c['legacy_alpha_index']+row[0]
    else:
        day,_=period(now)
        if db.execute('SELECT COUNT(*) FROM scientific_attempts WHERE day=?',(day,)).fetchone()[0]>=c['scheduler']['candidate_starts_per_day']:return False
        with db:
            cur=db.execute('INSERT INTO scientific_attempts(candidate,day,utc) VALUES(?,?,?)',(gid,day,utc()));index=c['legacy_alpha_index']+cur.lastrowid
            event(db,'scientific_attempt_reserved',candidate=gid,alpha_index=index,batch=batch,day=day)
    results={}
    for phase,interval,stress in [('training',c['training'],'nominal'),('validation',c['validation'],'nominal'),
                                  ('diagnostic',c['diagnostic'],'nominal'),('double_cost',c['diagnostic'],'double_cost'),('delayed',c['diagnostic'],'delayed')]:
        results[phase]=backtest(db,root,m,f,gid,p['genes'],phase,interval,stress,evaluator)
    control=backtest(db,root,m,f,'BTC_HALF','BTC_HALF','control',c['diagnostic'],evaluator=evaluator)
    row=db.execute('SELECT body FROM statistics WHERE candidate=?',(gid,)).fetchone()
    if row:stat=json.loads(row[0])
    else:
        from research.discovery_evolution.statistics import infer
        if results['diagnostic']['valid'] and control['valid']:
            stat=infer(book(root,results['diagnostic'])['equity'],book(root,control)['equity'],index,c)
        else:stat={'verdict':'UNDEFINED_INVALID','p':None,'alpha_index':index,'confirmed_trading_candidate':False}
        with db:
            db.execute('INSERT INTO statistics VALUES(?,?,?,?)',(gid,index,canonical(stat),utc()))
            event(db,'conditional_statistic_completed',candidate=gid,alpha_index=index,p=stat['p'],confirmed_trading_candidate=False)
    view={'id':gid,'genes':p['genes'],'rule':p['rule'],'cutoff':c['feedback_cutoff'],'frequency_episodes':discovery['bounded_episodes'],
          'source':p['origin'],'training':{'interval':c['training'],'valid':results['training']['valid'],'metrics':metrics(results['training']['metrics'])},
          'validation':{'interval':c['validation'],'valid':results['validation']['valid'],'metrics':metrics(results['validation']['metrics'])}}
    feedback={'candidate':gid,'proposal':p['id'],'batch':batch,'origin':p['origin'],'request':p['request'],'training_view':view,
              'diagnostic_only':{k:{'valid':results[k]['valid'],'metrics':metrics(results[k]['metrics'])} for k in ('diagnostic','double_cost','delayed')},
              'statistics':stat,'valid':all(v['valid'] for v in results.values()) and discovery.get('valid',True),
              'contamination':c['history_status'],'confirmed_trading_candidate':False,'new_market_discovery':False,'orders_allowed':False,'utc':utc()}
    with db:
        db.execute('INSERT INTO feedback VALUES(?,?,?,?)',(gid,batch,canonical(feedback),utc()))
        event(db,'feedback_completed',batch=batch,candidate=gid,origin=p['origin'],request=p['request'],training_feedback_hash=digest(view))
    atomic(Path(root)/'feedback'/f'{gid}.json',feedback);return True


def tick(db,root,mailbox,get_market,evaluator=default_evaluator,now=None,discovery_fn=None):
    c=load();ingest(db,mailbox);day,_=period(now)
    count=db.execute('SELECT COUNT(*) FROM scientific_attempts WHERE day=?',(day,)).fetchone()[0]
    unresolved=db.execute('SELECT candidate FROM scientific_attempts WHERE candidate NOT IN (SELECT candidate FROM feedback) LIMIT 1').fetchone()
    if count>=c['scheduler']['candidate_starts_per_day'] and not unresolved:
        ensure_request(db,mailbox);return 'WAIT_DAILY_COMPUTE_BUDGET'
    number,batch,reason=freeze_next(db,mailbox,now)
    if reason:return reason
    pending=[p for p in batch['entries'] if not db.execute('SELECT 1 FROM feedback WHERE candidate=?',(p['gene_id'],)).fetchone()]
    if pending:
        lease(root,'PREPARING_MARKET',batch=number);m,f=get_market();p=pending[0]
        discovery=inbox(db,root,m,f,number,p,discovery_fn)
        if not evaluate_candidate(db,root,m,f,number,p,discovery,evaluator,now):return 'WAIT_DAILY_COMPUTE_BUDGET'
    if all(db.execute('SELECT 1 FROM feedback WHERE candidate=?',(p['gene_id'],)).fetchone() for p in batch['entries']):
        with db:
            db.execute('INSERT INTO closed VALUES(?,?)',(number,utc()));event(db,'batch_closed',batch=number)
        ensure_request(db,mailbox)
    return 'PROGRESSED'


def snapshot(db,root,mailbox):
    c=load();counts={t:db.execute('SELECT COUNT(*) FROM '+t).fetchone()[0] for t in ('batches','closed','proposals','candidates','scientific_attempts','attempts','backtests','feedback','requests','ingested')}
    current=[r[0] for r in db.execute('SELECT id FROM batches WHERE id NOT IN (SELECT batch FROM closed)')]
    old=meta(db,'bootstrap')['inherited'];last=db.execute('SELECT body,hash FROM events ORDER BY id DESC LIMIT 1').fetchone()
    worker=live_lease(root);broker=live_lease(mailbox)
    def computing(value,phase):
        if not value or value['phase']!=phase:return False
        return True if value.get('pid_verified') else None
    discovery_flags=[computing(worker,'DISCOVERY'),computing(broker,'AI_TRANSPORT')]
    api=None;api_path=Path(mailbox)/'api.sqlite'
    if api_path.exists():
        from .broker import budget
        adb=sqlite3.connect('file:'+api_path.as_posix()+'?mode=ro',uri=True)
        try:
            api=budget(adb);api['provider_responses']=adb.execute("SELECT COUNT(*) FROM results WHERE json_extract(body,'$.state')='COMPLETE'").fetchone()[0]
            api['uncertain_attempts']=adb.execute("SELECT COUNT(*) FROM reservations WHERE id NOT IN (SELECT attempt FROM results) OR id IN (SELECT attempt FROM results WHERE json_extract(body,'$.state')='UNCERTAIN')").fetchone()[0]
        finally:adb.close()
    latest_state=Path(root)/'status.json';state=json.loads(latest_state.read_text()).get('state') if latest_state.exists() else 'INITIALIZING'
    return {'contract':c['id'],'state':state,'discovery_computing':True if True in discovery_flags else (None if None in discovery_flags else False),
        'evolution_computing':computing(worker,'BACKTEST'),'worker_phase':worker,'broker_phase':broker,
        'current_batches':current,'batches_closed':counts['closed'],'unique_candidates_completed':counts['feedback'],
        'AI_candidates_completed':db.execute("SELECT COUNT(*) FROM feedback WHERE json_extract(body,'$.origin')='AI_AUTHORED'").fetchone()[0],
        'local_candidates_completed':db.execute("SELECT COUNT(*) FROM feedback WHERE json_extract(body,'$.origin')!='AI_AUTHORED'").fetchone()[0],
        'valid_candidates_completed':db.execute("SELECT COUNT(*) FROM feedback WHERE json_extract(body,'$.valid')=1").fetchone()[0],
        'unique_configuration_hypotheses':counts['proposals'],'confirmed_market_discoveries':0,
        'known_rule_definitions':db.execute("SELECT COUNT(*) FROM hypotheses WHERE kind='mechanism'").fetchone()[0],
        'frequency_computations':db.execute("SELECT COUNT(*) FROM discoveries WHERE source='continuous_scheduler'").fetchone()[0],
        'statistical_tests_with_pvalue':db.execute("SELECT COUNT(*) FROM statistics WHERE json_extract(body,'$.p') IS NOT NULL").fetchone()[0],
        'lifetime_alpha_index':c['legacy_alpha_index']+counts['scientific_attempts'],'historical_registry':old,
        'remaining_unregistered_K':remaining(db),'api_budget':api,'counts':counts,'last_progress_utc':json.loads(last[0])['utc'],
        'last_event_hash':last[1],'next_batch_creation':'after current batch feedback closes; no lifetime batch cap',
        'orders_allowed':False,'sealed_access':False,'confirmed_trading_candidate':False}


def audit(root,mailbox):
    db=sqlite3.connect('file:'+(Path(root)/'research.sqlite').as_posix()+'?mode=ro',uri=True);db.execute('BEGIN')
    try:verify(db);result=snapshot(db,root,mailbox);result['hash_chain']='PASS';return result
    finally:db.rollback();db.close()


def run(root,mailbox,inputs,bootstrap):
    from research.phase2_v2.broker import broker_lock
    root=Path(root);root.mkdir(parents=True,exist_ok=True);c=load()
    with broker_lock(root):
        db=connect(root)
        try:
            initialize(db,json.loads(Path(bootstrap).read_text()),binding(inputs,bootstrap))
            if shutil.disk_usage(root).free<c['resources']['disk_reserve_bytes']:state='WAIT_DISK_RESERVE'
            elif (root/'research.sqlite').stat().st_size>c['resources']['ledger_max_bytes']:state='WAIT_LEDGER_CAPACITY'
            else:state=tick(db,root,mailbox,lambda:market(inputs))
            lease(root,'DONE' if state=='PROGRESSED' else 'WAIT',state=state)
            result=snapshot(db,root,mailbox);result['state']=state;atomic(root/'status.json',result);return result
        finally:db.close()
