"""Durable successor batches: discovery -> inbox -> unchanged engine -> feedback."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
from dataclasses import replace
from research.phase2_v2.market import canonical, digest, load_market
from research.phase2_v2.engine import evaluate
from research.phase2_v2.runtime import atomic, utc
from research.phase2_v2.broker import broker_lock
from research.phase2_v2.inputs import guarded_rows
from research.phase2_v2.contract import load as phase2
from research.anomaly_lab.rules import prepare
from research.anomaly_lab.runtime import binding as old_binding
from .contract import load
from .discovery import discover
from .statistics import design, infer

TABLES = ('meta','cycles','discoveries','inbox','candidates','attempts','backtests','stat_reservations','statistics','feedback','completed','events')


def connect(root):
    root = Path(root); root.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(root/'research.sqlite', timeout=20)
    db.execute('PRAGMA journal_mode=WAL'); db.execute('PRAGMA synchronous=FULL')
    db.executescript('''
    CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY,body TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS cycles(id INTEGER PRIMARY KEY,body TEXT NOT NULL,utc TEXT);
    CREATE TABLE IF NOT EXISTS discoveries(id TEXT PRIMARY KEY,cycle INTEGER,body TEXT NOT NULL,utc TEXT);
    CREATE TABLE IF NOT EXISTS inbox(id TEXT PRIMARY KEY,cycle INTEGER,body TEXT NOT NULL,utc TEXT);
    CREATE TABLE IF NOT EXISTS candidates(id TEXT PRIMARY KEY,hypothesis TEXT UNIQUE,cycle INTEGER,body TEXT NOT NULL,utc TEXT);
    CREATE TABLE IF NOT EXISTS attempts(id INTEGER PRIMARY KEY AUTOINCREMENT,key TEXT UNIQUE,kind TEXT,body TEXT,utc TEXT);
    CREATE TABLE IF NOT EXISTS backtests(key TEXT PRIMARY KEY,candidate TEXT,phase TEXT,body TEXT NOT NULL,utc TEXT);
    CREATE TABLE IF NOT EXISTS stat_reservations(id INTEGER PRIMARY KEY AUTOINCREMENT,candidate TEXT UNIQUE,utc TEXT);
    CREATE TABLE IF NOT EXISTS statistics(candidate TEXT PRIMARY KEY,alpha_index INTEGER UNIQUE,body TEXT NOT NULL,utc TEXT);
    CREATE TABLE IF NOT EXISTS feedback(candidate TEXT PRIMARY KEY,cycle INTEGER,body TEXT NOT NULL,utc TEXT);
    CREATE TABLE IF NOT EXISTS completed(cycle INTEGER PRIMARY KEY,utc TEXT);
    CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY,body TEXT,previous TEXT,hash TEXT UNIQUE);
    ''')
    for table in TABLES:
        for action in ('UPDATE','DELETE'):
            db.execute(f"CREATE TRIGGER IF NOT EXISTS {table}_immutable_{action} BEFORE {action} ON {table} BEGIN SELECT RAISE(ABORT,'immutable_research_evidence'); END")
    db.commit(); return db


def event(db, kind, **body):
    row = db.execute('SELECT hash FROM events ORDER BY id DESC LIMIT 1').fetchone(); previous = row[0] if row else 'GENESIS'
    encoded = canonical({'utc': utc(), 'kind': kind, **body})
    db.execute('INSERT INTO events(body,previous,hash) VALUES(?,?,?)', (encoded,previous,digest([encoded,previous])))


def source_binding(inputs, bootstrap):
    here = Path(__file__).resolve().parent
    return {'contract': digest(load()), 'code': {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(here.glob('*.py'))},
            'predecessor_and_inputs': old_binding(inputs), 'bootstrap_sha256': hashlib.sha256(Path(bootstrap).read_bytes()).hexdigest()}


def initialize(db, bootstrap, bound):
    row = db.execute("SELECT body FROM meta WHERE key='binding' OR key LIKE 'binding_repair:%' ORDER BY key DESC LIMIT 1").fetchone()
    if row:
        previous=json.loads(row[0])
        if previous != bound:
            # Only a runtime integration repair BEFORE the first batch can be refrozen.
            # Every prior binding and event is retained. No endpoint/data/pool change.
            differences={k for k in previous.get('code',{}) if previous['code'][k]!=bound.get('code',{}).get(k)}
            if (set(previous)!=set(bound) or 'code' not in previous or
                any(previous[k]!=bound[k] for k in previous if k!='code') or
                set(previous['code'])!=set(bound['code']) or not differences or
                not differences.issubset({'runtime.py','deploy.py'}) or
                any(db.execute('SELECT COUNT(*) FROM '+t).fetchone()[0] for t in TABLES if t not in ('meta','events'))):
                raise ValueError('frozen_binding_changed')
            with db:
                n=db.execute("SELECT COUNT(*) FROM meta WHERE key LIKE 'binding_repair:%'").fetchone()[0]+1
                db.execute('INSERT INTO meta VALUES(?,?)',(f'binding_repair:{n:04d}',canonical(bound)))
                event(db,'pre_result_runtime_repair_frozen',previous_binding=digest(previous),binding=bound,changed_modules=sorted(differences),results_before_repair=0)
        return
    c = load(); pool = bootstrap['pool']; seen = set(bootstrap['seen_gene_ids'])
    if bootstrap['contract'] != digest(c) or bootstrap['pool_digest'] != digest(pool): raise ValueError('bootstrap_contract')
    if len(pool)>c['budgets']['pool_max'] or len({p['gene_id'] for p in pool}) != len(pool) or len({p['hypothesis_id'] for p in pool}) != len(pool):
        raise ValueError('pool_not_novel')
    if any(p['gene_id'] in seen or p['root_cutoff']>c['training'][1] or digest(p['genes'])!=p['gene_id'] for p in pool):
        raise ValueError('legacy_duplicate_or_future_root')
    if bootstrap['inherited']['api_calls'] != c['api_limits']['calls']: raise ValueError('api_budget_mismatch')
    with db:
        for key,value in [('binding',bound),('bootstrap',bootstrap),('design',design(c))]: db.execute('INSERT INTO meta VALUES(?,?)',(key,canonical(value)))
        event(db,'successor_experiment_frozen',binding=bound,pool_digest=bootstrap['pool_digest'],design=design(c),inherited=bootstrap['inherited'])


def freeze_next(db, bootstrap):
    c = load(); active = db.execute('SELECT id,body FROM cycles WHERE id NOT IN (SELECT cycle FROM completed) ORDER BY id LIMIT 1').fetchone()
    if active: return active[0],json.loads(active[1])
    used = {r[0] for r in db.execute('SELECT id FROM discoveries')}
    # Also include frozen-but-uncomputed entries after a crash.
    for body, in db.execute('SELECT body FROM cycles'):
        used.update(p['hypothesis_id'] for p in json.loads(body)['entries'])
    remaining = [p for p in bootstrap['pool'] if p['hypothesis_id'] not in used]
    if not remaining: return None,None
    number = db.execute('SELECT COUNT(*) FROM cycles').fetchone()[0]+1
    if number>c['budgets']['cycles_max']: raise ValueError('cycle_budget_violation')
    prior = [json.loads(r[0]) for r in db.execute('SELECT body FROM feedback WHERE cycle=? ORDER BY candidate',(number-1,))]
    risk = any(not r['training'].get('valid') or r['training'].get('metrics',{}).get('mdd',1)>.35 for r in prior)
    rare = any(r['discovery_episodes']<20 for r in prior)
    remaining.sort(key=lambda p:(p['genes']['asset_weight_cap'] if risk else 0,p['hypothesis']['rule']['horizon'] if rare else 0,p['hypothesis_id']))
    body = {'cycle':number,'entries':remaining[:c['budgets']['batch_size']], 'contract':digest(c),
            'prior_feedback_hashes':[digest(r) for r in prior],'ordering_inputs':'prior-training MDD/invalid receipts and episode sparsity ONLY; no test scores',
            'training':c['training'],'test':c['test'],'null':c['statistics'],'frozen_utc':utc()}
    with db:
        db.execute('INSERT INTO cycles VALUES(?,?,?)',(number,canonical(body),utc())); event(db,'batch_frozen',cycle=number,batch_hash=digest(body),parents=body['prior_feedback_hashes'])
    return number,body


def publish_discovery(db, root, m, f, cycle, entry):
    hid=entry['hypothesis_id']; row=db.execute('SELECT body FROM discoveries WHERE id=?',(hid,)).fetchone()
    if row: result=json.loads(row[0])
    else:
        result=discover(m,f,entry['hypothesis']['rule'],load()['training'])
        result.update(hypothesis_id=hid,root_receipt=entry['root_receipt'],root_hypothesis=entry['root_hypothesis'])
        message={'id':hid,'cycle':cycle,'genes':entry['genes'],'gene_id':entry['gene_id'],'discovery_hash':digest(result),
                 'root_receipt':entry['root_receipt'],'mapping':entry['mapping'],'cutoff':load()['training'][1],'orders_allowed':False}
        with db:
            db.execute('INSERT INTO discoveries VALUES(?,?,?,?)',(hid,cycle,canonical(result),utc()))
            db.execute('INSERT INTO inbox VALUES(?,?,?,?)',(hid,cycle,canonical(message),utc()))
            event(db,'discovery_to_research_inbox',cycle=cycle,hypothesis=hid,receipt=entry['root_receipt'],discovery_hash=digest(result))
    message=json.loads(db.execute('SELECT body FROM inbox WHERE id=?',(hid,)).fetchone()[0])
    atomic(Path(root)/'inbox'/f'{hid}.json',message)
    gid=entry['gene_id']
    if not db.execute('SELECT 1 FROM candidates WHERE id=?',(gid,)).fetchone():
        if message['orders_allowed'] or message['gene_id']!=digest(message['genes']) or message['cutoff']>=load()['test'][0]: raise ValueError('unsafe_inbox')
        with db:
            db.execute('INSERT INTO candidates VALUES(?,?,?,?,?)',(gid,hid,cycle,canonical(entry),utc()))
            event(db,'inbox_consumed_evolution_candidate',cycle=cycle,candidate=gid,hypothesis=hid,root_receipt=entry['root_receipt'])


def reserve(db,key,kind,spec):
    row=db.execute('SELECT id FROM attempts WHERE key=?',(key,)).fetchone()
    if row: return row[0]
    with db:
        cursor=db.execute('INSERT INTO attempts(key,kind,body,utc) VALUES(?,?,?,?)',(key,kind,canonical(spec),utc()))
        event(db,'backtest_reserved',attempt=cursor.lastrowid,key=key,kind_of_computation=kind)
    return cursor.lastrowid


def checked_evaluate(m,f,strategy,interval,stress):
    value=evaluate(m,strategy,[interval],cost_mult=2. if stress=='double_cost' else 1.,delay_entries=stress=='delayed')
    # Outcome-time integrity rejects a whole candidate; it never rewrites its signals.
    for ep in value['episodes']:
        j=m.assets.index(ep['asset']); lo=m.dates.get_indexer([ep['start']])[0]; end=ep['end'] or interval[1]; hi=m.dates.get_indexer([end])[0]
        if not f['quality'][lo:hi+1,j].all(): raise ValueError('invalid_held_candle:'+ep['asset'])
    return value


def backtest(db,m,f,gid,genes,phase,interval,stress='nominal',kind='candidate',evaluator=checked_evaluate):
    key=digest([gid,phase,interval,stress]); row=db.execute('SELECT body FROM backtests WHERE key=?',(key,)).fetchone()
    if row: return json.loads(row[0])
    attempt=reserve(db,key,kind,{'candidate':gid,'phase':phase,'interval':interval,'stress':stress,'engine':'frozen_phase2_v2'})
    try:
        result=evaluator(m,f,genes,interval,stress)
        body={'valid':True,'attempt':attempt,'metrics':result['metrics'],'equity':result['equity'],'audit':result['audit']}
    except (ValueError,AssertionError,FloatingPointError) as exc:
        body={'valid':False,'attempt':attempt,'error':str(exc),'verdict':'UNDEFINED_INVALID','metrics':None,'equity':None}
    with db:
        db.execute('INSERT INTO backtests VALUES(?,?,?,?,?)',(key,gid,phase,canonical(body),utc()))
        event(db,'backtest_completed',candidate=gid,phase=phase,key=key,attempt=attempt,valid=body['valid'])
    return body


def evaluate_candidate(db,root,m,f,cycle,entry,evaluator=checked_evaluate):
    c=load(); gid=entry['gene_id']
    row=db.execute('SELECT body FROM feedback WHERE candidate=?',(gid,)).fetchone()
    if row:
        atomic(Path(root)/'feedback'/f'{gid}.json',json.loads(row[0])); return
    sr=db.execute('SELECT id FROM stat_reservations WHERE candidate=?',(gid,)).fetchone()
    if not sr:
        with db:
            cursor=db.execute('INSERT INTO stat_reservations(candidate,utc) VALUES(?,?)',(gid,utc()))
            event(db,'statistic_reserved',candidate=gid,alpha_index=c['legacy_alpha_debt']+cursor.lastrowid)
        alpha_index=c['legacy_alpha_debt']+cursor.lastrowid
    else: alpha_index=c['legacy_alpha_debt']+sr[0]
    training=backtest(db,m,f,gid,entry['genes'],'training',c['training'],evaluator=evaluator)
    nominal=backtest(db,m,f,gid,entry['genes'],'test',c['test'],evaluator=evaluator)
    double=backtest(db,m,f,gid,entry['genes'],'double_cost',c['test'],'double_cost',evaluator=evaluator)
    delayed=backtest(db,m,f,gid,entry['genes'],'delayed',c['test'],'delayed',evaluator=evaluator)
    reference=backtest(db,m,f,'BTC_HALF','BTC_HALF','control',c['test'],kind='control',evaluator=evaluator)
    row=db.execute('SELECT body FROM statistics WHERE candidate=?',(gid,)).fetchone()
    if row: statistics=json.loads(row[0])
    else:
        statistics=(infer(nominal['equity'],reference['equity'],alpha_index,c) if nominal['valid'] and reference['valid'] else
                    {'verdict':'UNDEFINED_INVALID','p':None,'alpha_index':alpha_index,'confirmed_trading_candidate':False})
        with db:
            db.execute('INSERT INTO statistics VALUES(?,?,?,?)',(gid,alpha_index,canonical(statistics),utc()))
            event(db,'statistic_completed',candidate=gid,alpha_index=alpha_index,verdict=statistics['verdict'],p=statistics['p'])
    discovery=json.loads(db.execute('SELECT body FROM discoveries WHERE id=?',(entry['hypothesis_id'],)).fetchone()[0])
    feedback={'candidate':gid,'hypothesis':entry['hypothesis_id'],'cycle':cycle,'root_receipt':entry['root_receipt'],
              'training':{k:training[k] for k in ('valid','metrics')} | {'error':training.get('error')},
              'test':{k:nominal[k] for k in ('valid','metrics')},'double_cost':double['metrics'],'delayed':delayed['metrics'],
              'discovery_episodes':discovery['bounded_episodes'],'statistics':statistics,
              'selection_feedback_scope':'ONLY training and training discovery; test/stress are development diagnostics excluded from successor ordering',
              'confirmed_trading_candidate':False,'orders_allowed':False,'utc':utc()}
    with db:
        db.execute('INSERT INTO feedback VALUES(?,?,?,?)',(gid,cycle,canonical(feedback),utc()))
        event(db,'feedback_committed',cycle=cycle,candidate=gid,hypothesis=entry['hypothesis_id'],feedback_hash=digest(feedback))
    atomic(Path(root)/'feedback'/f'{gid}.json',feedback)


def work(db,root,m,f,bootstrap,evaluator=checked_evaluate):
    cycle,batch=freeze_next(db,bootstrap)
    if cycle is None: return snapshot(db)
    for entry in batch['entries']: publish_discovery(db,root,m,f,cycle,entry)
    for entry in batch['entries']:
        if not db.execute('SELECT 1 FROM feedback WHERE candidate=?',(entry['gene_id'],)).fetchone():
            evaluate_candidate(db,root,m,f,cycle,entry,evaluator); break
    if all(db.execute('SELECT 1 FROM feedback WHERE candidate=?',(e['gene_id'],)).fetchone() for e in batch['entries']):
        with db:
            db.execute('INSERT INTO completed VALUES(?,?)',(cycle,utc())); event(db,'batch_closed',cycle=cycle)
    return snapshot(db)


def snapshot(db):
    bootstrap=json.loads(db.execute("SELECT body FROM meta WHERE key='bootstrap'").fetchone()[0]); counts={k:db.execute('SELECT COUNT(*) FROM '+k).fetchone()[0] for k in TABLES if k!='meta'}
    last=db.execute('SELECT body,hash FROM events ORDER BY id DESC LIMIT 1').fetchone(); remaining=len(bootstrap['pool'])-counts['feedback']
    active=[r[0] for r in db.execute('SELECT id FROM cycles WHERE id NOT IN (SELECT cycle FROM completed)')]
    attempted=db.execute("SELECT COUNT(DISTINCT candidate) FROM backtests WHERE candidate!='BTC_HALF'").fetchone()[0]
    actual_statistics=db.execute("SELECT COUNT(*) FROM statistics WHERE json_extract(body,'$.p') IS NOT NULL").fetchone()[0]
    failed=db.execute("SELECT COUNT(*) FROM feedback WHERE json_extract(body,'$.test.valid')=0").fetchone()[0]
    return {'contract':load()['id'],'state':'RUNNING' if remaining else 'IDLE_NO_NEW_WORK','idle_reason':None if remaining else 'FROZEN_AUTHORIZED_POOL_EXHAUSTED',
            'discovery_active':bool(remaining),'evolution_active':bool(remaining),'current_cycles':active,'closed_cycles':counts['completed'],
            'unique_new_hypotheses':counts['discoveries'],'legacy_handoff_receipts':len(bootstrap['legacy_receipts']),
            'legacy_unique_hypotheses':len({r['hypothesis_id'] for r in bootstrap['legacy_receipts']}),
            'legacy_repeated_handoffs':len(bootstrap['legacy_receipts'])-len({r['hypothesis_id'] for r in bootstrap['legacy_receipts']}),
            'legacy_unique_proposed_genes':len({digest(r['genes']) for r in bootstrap['legacy_receipts']}),
            'accepted_new_genes':counts['candidates'],'candidates_actually_evaluated':attempted,'failed_candidates':failed,
            'backtest_calculations_completed':counts['backtests'],'backtest_attempts_reserved':counts['attempts'],
            'statistical_attempts_reserved':counts['stat_reservations'],'statistical_tests_with_pvalue':actual_statistics,
            'conservative_lifetime_alpha_index':load()['legacy_alpha_debt']+counts['stat_reservations'],
            'inherited':bootstrap['inherited'],'global_historical_gene_ids':len(bootstrap['seen_gene_ids']),
            'authorized_pool_remaining':remaining,'last_progress_utc':json.loads(last[0])['utc'],'last_event_hash':last[1],
            'next_automatic_action':'resume active candidate / freeze successor from training feedback' if remaining else 'idle health check; no repeat evaluations or API calls',
            'statistical_design':json.loads(db.execute("SELECT body FROM meta WHERE key='design'").fetchone()[0]),
            'orders_allowed':False,'sealed_access':False,'new_api_calls':0,'counts':counts}


def audit(root):
    db=sqlite3.connect('file:'+(Path(root)/'research.sqlite').as_posix()+'?mode=ro',uri=True); db.execute('BEGIN')
    try:
        prior='GENESIS'
        for body,previous,hash_ in db.execute('SELECT body,previous,hash FROM events ORDER BY id'):
            if previous!=prior or digest([body,previous])!=hash_: raise ValueError('hash_chain_failure')
            prior=hash_
        result=snapshot(db); result['hash_chain']='PASS'; return result
    finally: db.rollback(); db.close()


def run(root,inputs,bootstrap_path):
    c=load(); root=Path(root); boot=json.loads(Path(bootstrap_path).read_text())
    if shutil.disk_usage(root.parent).free<c['budgets']['disk_reserve_bytes']: raise ValueError('disk_reserve')
    with broker_lock(root):
        db=connect(root)
        try:
            initialize(db,boot,source_binding(inputs,bootstrap_path))
            if (root/'research.sqlite').stat().st_size>c['budgets']['ledger_bytes']: raise ValueError('ledger_budget')
            if db.execute('SELECT COUNT(*) FROM feedback').fetchone()[0]==len(boot['pool']): result=snapshot(db)
            else:
                m=load_market(Path(inputs),c['development'][1]); production={}
                with (Path(inputs)/'production_targets.csv').open('rb') as stream:
                    for r in guarded_rows(stream,phase2()): production[r['date'][:10]]=(r['execution_target_asset'],float(r['execution_target_exposure']))
                f=prepare(m,production); m=restricted_market(m,f); result=work(db,root,m,f,boot)
            atomic(root/'status.json',result); return result
        finally: db.close()


def restricted_market(m,f):
    # Native archived market arrays are intentionally read-only.
    return replace(m,eligible=m.eligible & f['eligible'])


if __name__=='__main__':
    p=argparse.ArgumentParser(); p.add_argument('--root',type=Path,required=True); p.add_argument('--inputs',type=Path); p.add_argument('--bootstrap',type=Path); p.add_argument('--audit',action='store_true')
    a=p.parse_args(); print(canonical(audit(a.root) if a.audit else run(a.root,a.inputs,a.bootstrap)))
