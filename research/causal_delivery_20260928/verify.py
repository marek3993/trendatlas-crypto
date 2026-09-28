"""Offline read-only audit/export of the terminal snapshot. Never runs strategies.

Only validate_payload/validate_response are imported from the frozen engine.
No evaluator, Store, API client, order adapter or live state is instantiated.
"""
import argparse
from collections import Counter, defaultdict
import csv
import gzip
import hashlib
import json
import math
from pathlib import Path
import sqlite3
import statistics
import sys

ENGINE = '53b6a5336ca1f7ce35b481a017f7e82396f3613c'
FINGERPRINT = 'eeb244ea6a79ef396f8f607696eebe08115b4a3a3bb16d4e74d0d251df0d8385'
MANIFEST_SHA = '1f92cd047b2d39cc071984f57485beaafbb560b935fd23109c9f121154af0abc'


def sha(path):
    with Path(path).open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def dump(path, obj):
    Path(path).write_text(json.dumps(obj, indent=2, sort_keys=True, allow_nan=False)+'\n', encoding='utf-8')


def table(path, rows):
    fields = list(dict.fromkeys(k for row in rows for k in row))
    with Path(path).open('w', encoding='utf-8', newline='') as f:
        w = csv.DictWriter(f, fields); w.writeheader()
        w.writerows({k:json.dumps(v, sort_keys=True) if isinstance(v, (dict, list)) else v for k,v in row.items()} for row in rows)


def readonly(path):
    db = sqlite3.connect(Path(path).resolve().as_uri()+'?mode=ro&immutable=1', uri=True)
    db.row_factory = sqlite3.Row
    assert db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
    assert not db.execute('PRAGMA foreign_key_check').fetchall()
    return db


def near(a, b):
    assert math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-9), (a, b)


def unpack(row):
    return {k:json.loads(gzip.decompress(row[k])) if k in ('daily','episodes','orders') else json.loads(row[k])
            for k in ('request','metrics','daily','episodes','orders','folds','audit')}


def book_metrics(book):
    daily = book['daily']; capital = book['request']['capital']
    nav = [capital]+[d['nav'] for d in daily]
    lr = [math.log(b/a) for a,b in zip(nav, nav[1:])]
    ret = [math.expm1(x) for x in lr]
    cagr = math.expm1(sum(lr)/len(lr)*365.25)
    sd = statistics.stdev(ret)
    sharpe = statistics.mean(ret)/sd*math.sqrt(365.25) if sd>1e-12 else 0
    # intrabar_mdd is the ledger's recorded cumulative high/low mark drawdown.
    mdd = max(d['intrabar_mdd'] for d in daily)
    closed = [e for e in book['episodes'] if e['closed']]
    m = dict(cagr=cagr,mdd=mdd,sharpe=sharpe,calmar=cagr/mdd if mdd else 0,
             no_best_day_cagr=math.expm1((sum(lr)-max(lr))/len(lr)*365.25),
             no_top3_cagr=math.expm1((sum(lr)-sum(sorted([max(0,e['log_growth']) for e in closed],reverse=True)[:3]))/len(lr)*365.25),
             trades=len(closed),median_holding_days=statistics.median(e['holding_days'] for e in closed) if closed else 0,
             profitable_folds=sum(f['cagr']>0 for f in book['folds']),worst_fold=min(f['cagr'] for f in book['folds']))
    for source, dest in [('fee','fee_usd'),('slippage','slippage_usd'),('funding_debit','funding_debit_usd'),('funding_credit','funding_credit_usd')]:
        m[dest] = sum(d[source] for d in daily)
    m['costs_usd'] = m['fee_usd']+m['slippage_usd']+m['funding_debit_usd']-m['funding_credit_usd']
    for k,v in m.items():
        if k in book['metrics']: near(v,book['metrics'][k])
    return m


def key(r):
    return (r['island'], int(r['seed']), r['arm'], r['slot'])


def audit(snapshot, engine, out, prior=None):
    out.mkdir(parents=True, exist_ok=True)
    files = read(snapshot/'transfer_manifest.json')
    for rel,meta in files.items():
        p = (snapshot/rel).resolve(); assert p.is_relative_to(snapshot.resolve())
        assert p.stat().st_size == meta['bytes'] and sha(p)==meta['sha256'], rel
    assert sha(snapshot/'frozen_manifest.json') == MANIFEST_SHA
    frozen_files=read(snapshot/'frozen_manifest.json')['files']
    for rel,expected in frozen_files.items():
        assert sha(engine/'research/causal_evolution'/rel)==expected, rel
    # Use the exact old pure JSON validator, never import current research machinery.
    sys.path.insert(0,str(engine.resolve()))
    from research.causal_evolution.designer import validate_payload, validate_response
    from research.causal_evolution.protocol import periods
    from research.causal_evolution.vendor.common import cid
    db=readonly(snapshot/'candidates.sqlite'); mail=readonly(snapshot/'mailbox/proposals.sqlite')
    meta={r['key']:json.loads(r['value']) for r in db.execute('SELECT * FROM meta')}
    assert meta['fingerprint']==FINGERPRINT and meta['status']=='SEALED'
    assert meta['search_frozen'] and meta['outer_opened'] and meta['failure'] is None
    counts={t:db.execute('SELECT COUNT(*) FROM '+t).fetchone()[0] for t in ('attempts','evaluations','candidates','trials','finalists','scores','populations')}
    assert counts==dict(attempts=7211,evaluations=7203,candidates=1126,trials=3415,finalists=144,scores=2400,populations=240)
    attempts=Counter(r[0] for r in db.execute('SELECT status FROM attempts'))
    assert attempts==dict(COMPLETE=7203,INTERRUPTED=8)
    assert not db.execute("SELECT cache_key FROM attempts WHERE status='COMPLETE' GROUP BY cache_key HAVING COUNT(*)!=1").fetchall()
    assert not db.execute("SELECT cache_key FROM evaluations EXCEPT SELECT cache_key FROM attempts WHERE status='COMPLETE'").fetchall()
    assert not db.execute("SELECT cache_key FROM attempts WHERE status='COMPLETE' EXCEPT SELECT cache_key FROM evaluations").fetchall()
    first_outer=db.execute("SELECT MIN(started) FROM attempts WHERE scope='outer'").fetchone()[0]
    last_trial=db.execute('SELECT MAX(created) FROM trials').fetchone()[0]
    last_development=db.execute("SELECT MAX(finished) FROM attempts WHERE scope!='outer'").fetchone()[0]
    assert last_trial<first_outer and last_development<first_outer
    finalists=read(snapshot/'frozen_finalists.json'); results=read(snapshot/'results.json')
    assert len(finalists)==144 and len(results)==72 and all(r['decision']=='REJECT' for r in results)
    assert finalists==[json.loads(r[0]) for r in db.execute('SELECT body FROM finalists ORDER BY run,slot')]
    assert all(f['selected_only_from_inner'] for f in finalists)
    groups=defaultdict(list)
    for f in finalists: groups[key(f)].append(f)
    for fs in groups.values(): assert sorted(f['origin'] for f in fs)==[2024,2025]
    api=[]; accepted=0; rejection=Counter(); uncertain=0; reserved=0
    for r in mail.execute('SELECT * FROM proposals ORDER BY created'):
        p=json.loads(r['payload']); v=json.loads(r['validation']); u=json.loads(r['usage'])
        assert r['created']<first_outer
        validate_payload(p)
        if r['state']=='COMPLETE':
            response=json.loads(r['response']); a,b=validate_response(response['content'],p)
            assert a==v['accepted'] and b==v['rejected']
            assert response['request']['messages'][1]['content']==r['payload']
        accepted+=len(v['accepted']); rejection.update(x['reason'] for x in v['rejected'])
        uncertain+=bool(u.get('uncertain')); reserved+=u.get('reserved_usd',0) if u.get('uncertain') else 0
        api.append(dict(id=r['id'],run=r['run'],generation=r['generation'],state=r['state'],created=r['created'],accepted=len(v['accepted']),rejections=v['rejected'],**u))
    assert len(api)==96 and accepted==177
    table(out/'api_calls.csv',api)
    sources=Counter(r[0] for r in db.execute('SELECT source FROM trials'))
    slots=[]
    for arm in ('deepseek','deterministic'):
        c=Counter(r[0] for r in db.execute('SELECT source FROM trials WHERE run LIKE ?',('%:'+arm,)))
        n=sum(c[s] for s in ('seed','deepseek','deterministic','deterministic_fallback'))
        assert n==624
        slots.append(dict(arm=arm,new_candidate_slots=n,**c))
    table(out/'arm_budget.csv',slots)
    audits=read(snapshot/'audit_results.json')
    assert len(audits)==144 and all(all(a[k] for k in ('pass_audit','true_prefix_ledger','true_prefix_signals','future_mutation_signals')) for a in audits)
    all_requests={}; scope_counts=Counter(); eval_audits=0
    allowed_dev=[p for o in (2024,2025) for p in periods(o) if p['scope']!='outer']
    for r in db.execute('SELECT cache_key,request,audit FROM evaluations'):
        req=json.loads(r['request']); a=json.loads(r['audit']); assert req['engine']==FINGERPRINT and a['pass_audit'] and not a['failures']
        assert req['track']==a['track']; eval_audits+=1; scope_counts[req['period']['scope']]+=1
        if req['period']['scope']!='outer': assert req['period'] in allowed_dev
        all_requests[json.dumps(req,sort_keys=True)]=r['cache_key']
    def lookup(req):
        k=all_requests[json.dumps(req,sort_keys=True)]
        return unpack(db.execute('SELECT * FROM evaluations WHERE cache_key=?',(k,)).fetchone())
    summary=[]; stress_rows=[]; capacity=[]; fold_rows=[]; rules=[]; exposures=[]; benchmark_books={}; expected_equity={}
    for r in results:
        fs=sorted(groups[key(r)],key=lambda f:f['origin'])
        assert r['candidates']==[f['id'] for f in fs]
        req=dict(benchmark=False,cash=False,capital=100,engine=FINGERPRINT,genes=fs[0]['genes'],period=dict(scope='outer',fold='continuous_frozen_schedule',start='2024-01-01',end='2025-12-31'),schedule=[dict(year=f['origin'],genes=f['genes']) for f in fs],stress='nominal',track=r['island'].split('_')[1])
        book=lookup(req); measured=book_metrics(book)
        for k,v in measured.items():near(v,r['metrics'][k])
        assert len(book['daily'])==731
        expected_equity[key(r)]=book['daily']
        ident={k:r[k] for k in ('island','seed','arm','slot')}
        for f in fs: rules.append(dict(**ident,year=f['origin'],candidate=f['id'],**f['genes']))
        for fold in book['folds']: fold_rows.append(dict(**ident,book='CONTINUOUS_PRIMARY',**fold))
        for s,metrics in r['stresses'].items():
            value=lookup(dict(req,stress=s)); checked=book_metrics(value)
            for k,v in checked.items():
                if k in metrics:near(v,metrics[k])
            stress_rows.append(dict(**ident,stress=s,**metrics))
        for i,n in enumerate(r['neighbors']):
            ns=[dict(year=f['origin'],genes=f['neighbors'][i]) for f in fs]
            value=lookup(dict(req,genes=ns[0]['genes'],schedule=ns)); checked=book_metrics(value)
            for k,v in checked.items():
                if k in n:near(v,n[k])
            stress_rows.append(dict(**ident,stress='neighbor_'+str(i+1),**n))
        for c in (100,1000,10000,100000):
            value=lookup(dict(req,capital=c)); book_metrics(value)
            capacity.append(dict(**ident,capital=c,**value['metrics']))
        summary.append(dict(**ident,decision=r['decision'],**r['metrics'],double_cost_cagr=r['stresses']['double_cost']['cagr'],later_bar_cagr=r['stresses']['later_bar']['cagr'],benchmark_cagr=r['benchmark']['cagr'],benchmark_mdd=r['benchmark']['mdd'],bootstrap_status=r['bootstrap']['status'],holm_pvalue=r['bootstrap']['holm_pvalue'],rejection_reasons=r['rejection_reasons']))
        for ep in book['episodes']:exposures.append(dict(**ident,**ep))
        track=req['track']
        if track not in benchmark_books:
            ref=next(json.loads(q) for q in all_requests if (lambda x:x['benchmark'] and x['track']==track and x['capital']==100 and x['period']==req['period'] and x['stress']=='nominal')(json.loads(q)))
            benchmark_books[track]=lookup(ref)
            b=benchmark_books[track]; bm=book_metrics(b)
            for k,v in bm.items():
                if k in r['benchmark']:near(v,r['benchmark'][k])
            expected_equity[('BTC_'+track,0,'benchmark','C')]=b['daily']
            summary.append(dict(island='BTC_'+track,seed=0,arm='benchmark',slot='C',decision='REFERENCE',**(b['metrics']|bm),double_cost_cagr='NOT_EVALUATED',later_bar_cagr='NOT_EVALUATED'))
            for fold in b['folds']:fold_rows.append(dict(island='BTC_'+track,seed=0,arm='benchmark',slot='C',book='CONTINUOUS_PRIMARY',**fold))
    actual_equity=defaultdict(list)
    with (snapshot/'equity.csv').open(encoding='utf-8') as f:
        for r in csv.DictReader(f):actual_equity[key(r)].append(r)
    assert set(actual_equity)==set(expected_equity)
    for k,days in expected_equity.items():
        assert len(actual_equity[k])==len(days)
        for expected,actual in zip(days,actual_equity[k]):
            assert expected['date']==actual['date'] and actual['book']=='CONTINUOUS_PRIMARY'
            for field,value in expected.items():
                if field!='date':near(value,float(actual[field]))
    # Original common table must match all 72 primary database results.
    original=list(csv.DictReader((snapshot/'all_results.csv').open(encoding='utf-8')))
    assert len(original)==72
    for r in results:
        t=next(t for t in original if key(t)==key(r))
        for k,v in r['metrics'].items():
            if isinstance(v,(int,float)) and not isinstance(v,bool):near(v,float(t[k]))
    table(out/'common_comparison.csv',summary);table(out/'continuous_annual_folds.csv',fold_rows)
    table(out/'continuous_stresses_neighbors.csv',stress_rows);table(out/'continuous_capacity.csv',capacity)
    table(out/'exact_rules.csv',rules);table(out/'episodes.csv',exposures)
    arm_results=[]
    for island in ('F_spot','G_spot','H_spot','D_perp'):
        for arm in ('deterministic','deepseek'):
            rs=[r for r in results if r['island']==island and r['arm']==arm]
            arm_results.append(dict(island=island,arm=arm,rows=len(rs),passed=sum(r['decision']!='REJECT' for r in rs),median_cagr=statistics.median(r['metrics']['cagr'] for r in rs),median_mdd=statistics.median(r['metrics']['mdd'] for r in rs),median_sharpe=statistics.median(r['metrics']['sharpe'] for r in rs),median_calmar=statistics.median(r['metrics']['calmar'] for r in rs)))
    table(out/'arms_descriptive_only.csv',arm_results)
    rejection_counts=Counter(x for r in results for x in r['rejection_reasons'])
    report=dict(status='PASS_DELIVERY_INTEGRITY_NOT_STRATEGY',decision=meta['decision'],engine_commit=ENGINE,fingerprint=FINGERPRINT,manifest_sha256=MANIFEST_SHA,files_verified=len(files),sqlite_integrity='ok',counts=counts,attempt_states=dict(attempts),evaluation_scopes=dict(scope_counts),last_trial=last_trial,last_development_finish=last_development,first_outer=first_outer,barrier_file_utc=read(snapshot/'mailbox/SEALED.json')['utc'],barrier_note='File is refreshed on outer resume; it is not the first freeze timestamp. All recorded hypotheses and development attempts precede first outer.',prospective_earliest_closed_day='2026-09-29',active_seconds=meta['active_seconds'],api=dict(calls=len(api),completed=sum(r['state']=='COMPLETE' for r in api),uncertain_calls=uncertain,reported_tokens=sum(r.get('total_tokens',0) for r in api),reported_cost_upper_usd=sum(r.get('usd',0) for r in api),uncertain_reserved_usd=reserved,reported_plus_uncertain_reserve_usd=sum(r.get('usd',0) for r in api)+reserved,accepted=accepted,rejection_records=dict(rejection),fallback_slots=sources['deterministic_fallback']),trial_sources=dict(sources),causal_prefix_audits=len(audits),stored_fill_lineage_audits=eval_audits,primary_rows_verified=72,benchmark_rows_verified=2,primary_days=731,equity_rows_verified=sum(len(x) for x in expected_equity.values()),nomination_records=144,statistical_rejection_counts=dict(rejection_counts),holm_values=sorted(set(r['bootstrap']['holm_pvalue'] for r in results)),max_actual_gross=max(r['metrics']['max_actual_gross'] for r in results),pareto_rows=len(read(snapshot/'pareto_front.json')),limitations=['Historical data previously studied; no globally sealed or prospective result','Binance spot / USD-M research proxies; not certified Hyperliquid fills','Actual perp gross can drift above target 1.25; this is not a hard exposure cap','Benchmark double-cost and delayed-fill books absent; explicitly NOT_EVALUATED, no new run','No million-dollar test in this frozen contract; capacity maximum is a tested point, not a venue guarantee','No evaluator or strategy replay performed by this verification'])
    if prior:
        preservation={}
        for rel,new,tables in [('candidates.sqlite',db,('attempts','evaluations','candidates','trials','finalists','scores','populations','orchestration_events')),('mailbox/proposals.sqlite',mail,('proposals',))]:
            previous=readonly(prior/rel)
            if rel=='candidates.sqlite':
                assert sha(prior/rel)=='5457c1d146ae3d7825dec926cb0d13b82ea1b13c596f578c98b48715254ad720'
            for t in tables:
                keys=[r[1] for r in previous.execute('PRAGMA table_info('+t+')') if r[5]]
                assert keys
                query='SELECT * FROM '+t+' WHERE '+' AND '.join(k+'=?' for k in keys)
                count=0
                for old in previous.execute('SELECT * FROM '+t):
                    current=new.execute(query,tuple(old[k] for k in keys)).fetchone()
                    assert current is not None and dict(current)==dict(old), (t,tuple(old[k] for k in keys))
                    count+=1
                preservation[rel+':'+t]=count
            previous.close()
        report['preserved_checkpoint_5087_rows']=preservation
    dump(out/'verification.json',report)
    db.close();mail.close()
    return report


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--snapshot',type=Path,required=True);p.add_argument('--engine',type=Path,required=True);p.add_argument('--out',type=Path,required=True);p.add_argument('--prior-checkpoint',type=Path);a=p.parse_args()
    print(json.dumps(audit(a.snapshot,a.engine,a.out,a.prior_checkpoint),indent=2))
