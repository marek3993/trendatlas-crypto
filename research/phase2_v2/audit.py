"""Read-only audit of v2 checkpoints, lineage and continuous stitched curve."""
import argparse
from collections import Counter
import json
from pathlib import Path
import sqlite3
from .contract import load
from .engine import curve_metrics
from .market import digest
from .runtime import status, quality

def report(root):
    root=Path(root);db=sqlite3.connect('file:'+str(root/'v2.sqlite')+'?mode=ro',uri=True)
    db.execute('BEGIN')  # One coherent SQLite read snapshot while workers continue.
    try:
        result=status(db);result['sqlite_integrity']=db.execute('PRAGMA quick_check').fetchone()[0]
        previous='GENESIS';audit_rows=0
        for stamp,kind,body,prior,h in db.execute('SELECT utc,kind,body,previous_hash,row_hash FROM events ORDER BY id'):
            if prior!=previous or digest([stamp,kind,body,prior])!=h:raise RuntimeError('v2_audit_chain')
            previous=h;audit_rows+=1
        result.update(audit_chain_valid=True,audit_chain_rows=audit_rows)
        result['duplicate_evaluations']=db.execute('SELECT count(*)-count(DISTINCT key) FROM evaluations').fetchone()[0]
        result['duplicate_genes']=db.execute('SELECT count(*)-count(DISTINCT genes) FROM candidates').fetchone()[0]
        result['membership']=[dict(origin=o,generation=g,role=r,count=n) for o,g,r,n in db.execute('SELECT origin,generation,role,count(*) FROM members GROUP BY origin,generation,role ORDER BY origin,generation,role')]
        result['selections']=[dict(origin=o,candidate=c,genes=json.loads(g),evidence=json.loads(e),frozen_utc=t) for o,c,g,e,t in db.execute('SELECT * FROM selections ORDER BY origin')]
        result['quality']=quality(db,result['stage'][0]) if result['stage'] else None
        populations={}
        if result['stage']:
            origin=result['stage'][0]
            for cid,source in db.execute('SELECT id,source FROM candidates WHERE origin<=?',(origin,)):
                arm='deepseek' if source.startswith('deepseek:') else 'deterministic' if source.startswith('deterministic:') else 'control'
                trials=[json.loads(r) for (r,) in db.execute('SELECT result FROM evaluations WHERE candidate_id=? AND origin=?',(cid,origin))]
                if not trials:continue
                bucket=populations.setdefault(arm,{'attempted_candidates':0,'complete_trials':0,'invalid_trials':0})
                bucket['attempted_candidates']+=1
                if len(trials)==3:
                    bucket['complete_trials']+=1;bucket['invalid_trials']+=any('failure' in r for r in trials)
            result['arm_attrition']=populations
        result['invalid_evaluations']=sum('failure' in json.loads(r) for (r,) in db.execute('SELECT result FROM evaluations'))
        curves=[];folds=[];assets={};episodes={};costs=turnover=0.;trades=0
        for origin,raw,finished in db.execute('SELECT * FROM test_books ORDER BY origin'):
            book=json.loads(raw)
            curves.extend({**r,'fold':origin} for r in book['equity']);folds.extend(book['folds'])
            costs+=book['metrics']['costs_usd'];trades+=book['metrics']['trades']
            turnover+=book['metrics']['turnover']*book['metrics']['elapsed_calendar_days']/365.25
            for r in book['assets']:assets[r['asset']]=assets.get(r['asset'],0)+r['log_contribution']
            for r in book['episodes']:episodes[r['id']]=r
        if curves:
            m=curve_metrics([r['date'] for r in curves],[r['equity'] for r in curves])
            import math
            years=m['elapsed_calendar_days']/365.25;growth=m['log_growth']
            positive=sorted((r for r in episodes.values() if r['status']=='CLOSED' and r['log_contribution']>0),key=lambda r:r['log_contribution'],reverse=True)
            da=max(assets,key=assets.get);de=max(episodes.values(),key=lambda r:r['log_contribution']) if episodes else None
            if not math.isclose(sum(assets.values()),growth,rel_tol=1e-8,abs_tol=1e-8):raise RuntimeError('stitched_asset_attribution')
            m.update(costs_usd=costs,cost_drag=costs/100/years,turnover=turnover/years,trades=trades,
                no_top3_trades_cagr=math.expm1((growth-sum(r['log_contribution'] for r in positive[:3]))/years) if len(positive)>=3 else None,
                dominant_asset=da if assets[da]>0 else None,asset_concentration=assets[da]/growth if growth>0 and assets[da]>0 else None,
                dominant_episode=de['id'] if de else None,trade_concentration=de['log_contribution']/growth if growth>0 and de and de['log_contribution']>0 else None,
                profitable_fold_fraction=sum(f['metrics']['net_return']>0 for f in folds)/len(folds),
                worst_fold=min(folds,key=lambda f:f['metrics']['net_return']))
            result['stitched_walk_forward']={'metrics':m,'equity':curves,'folds':folds,'assets':assets,'episodes':list(episodes.values()),
                'scope':'previously_seen_development_nested_selection_not_independent_outer_OOS'}
        else:result['stitched_walk_forward']=None
        response_files=list((root/'mailbox/responses').glob('*.json'))
        result['api_responses']=[json.loads(p.read_text()) for p in response_files]
        result['api_requests']=[{'hash':p.stem,'payload':json.loads(p.read_text())['payload']} for p in (root/'mailbox/requests').glob('*.json')]
        return result
    finally:db.close()

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);a=p.parse_args()
    print(json.dumps(report(a.root),allow_nan=False))
