"""Attribute fixed rejected references from a verified immutable backup; no replay."""
import argparse
from collections import Counter, defaultdict
import csv
import gzip
import hashlib
import json
import math
from pathlib import Path
import sqlite3

HERE = Path(__file__).resolve().parent
DELIVERY = HERE.parent/'causal_delivery_20260928'
REFERENCES = {'F': ('F_spot', '4517', 'deterministic', 'A'),
              'D': ('D_perp', '4517', 'deterministic', 'B')}


def sha(path):
    with Path(path).open('rb') as f:return hashlib.file_digest(f, 'sha256').hexdigest()


def read_csv(name, folder='derived'):
    with (DELIVERY/folder/(name+'.csv')).open() as f:return list(csv.DictReader(f))


def selected(row, ident):
    return tuple(str(row[k]) for k in ('island', 'seed', 'arm', 'slot')) == ident


def summarize(book):
    daily = book['daily'];episodes = book['episodes'];m = book['metrics']
    closed = [e for e in episodes if e['closed']]
    top = sorted(closed, key=lambda e: max(0, e['log_growth']), reverse=True)[:3]
    logs = math.log(daily[-1]['nav']/100)
    removed = math.expm1((logs-sum(e['log_growth'] for e in top))/len(daily)*365.25)
    if abs(removed-m['no_top3_cagr']) > 1e-9:raise ValueError('episode_reconciliation')
    trough = next(i for i, d in enumerate(daily) if abs(d['intrabar_mdd']-m['mdd']) < 1e-12)
    peak = max(range(trough+1), key=lambda i: daily[i]['nav_high'])
    assets = defaultdict(float)
    for e in episodes:assets[e['asset']] += e['pnl_usd']
    returns = [];previous = 100
    for d in daily:
        returns.append({'date': d['date'], 'return': d['nav']/previous-1, 'gross': d['gross']})
        previous=d['nav']
    return {'metrics': m, 'annual_folds': book['folds'], 'all_episodes': episodes,
            'top_three_whole_closed_episodes': top,
            'top_three_pnl_usd': sum(e['pnl_usd'] for e in top),
            'other_episodes_pnl_usd': sum(e['pnl_usd'] for e in episodes if e not in top),
            'no_top3_recomputed_cagr': removed,
            'max_drawdown_peak_day': daily[peak], 'max_drawdown_first_trough_day': daily[trough],
            'drawdown_attribution_precision': 'daily envelopes of stored 4h book; no invented intraday timestamp',
            'asset_episode_pnl_usd': dict(assets),
            'cash_days': sum(d['gross'] < 1e-10 for d in daily),
            'first_exposed_day': next((d['date'] for d in daily if d['gross'] > 1e-10), None),
            'worst_days': sorted(returns, key=lambda d: d['return'])[:10],
            'order_end_reasons': dict(Counter(o['reason'] for o in book['orders']))}


def effective_genes(g):
    active = ['family', 'signal', 'cadence', 'confirm', 'hysteresis']
    if g['family'] == 'F':active += ['scope']
    elif g['family'] == 'G':active += ['satellite', 'satellite_k']
    elif g['family'] == 'H':active += ['top_k', 'weighting']
    else:
        active += ['recipe', 'gross']
        if g['recipe'] != 'btc_regime':active += ['top_k', 'weighting']
    return {k: g[k] for k in active}


def analyze(snapshot, output):
    snapshot = Path(snapshot).resolve();output = Path(output).resolve()
    if output.is_relative_to(snapshot):raise ValueError('cannot_write_snapshot')
    manifest = json.loads((snapshot/'transfer_manifest.json').read_text())
    for name, record in manifest.items():
        if sha(snapshot/name) != record['sha256']:raise ValueError('snapshot_hash_mismatch:'+name)
    before = {name: sha(snapshot/name) for name in ('candidates.sqlite', 'mailbox/proposals.sqlite')}
    db = sqlite3.connect((snapshot/'candidates.sqlite').as_uri()+'?mode=ro&immutable=1', uri=True)
    db.row_factory=sqlite3.Row
    if db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':raise ValueError('integrity')
    finalists = json.loads((DELIVERY/'raw/frozen_finalists.json').read_text())
    references = {}
    for family, ident in REFERENCES.items():
        fs = sorted([f for f in finalists if selected(f, ident)], key=lambda f:f['origin'])
        schedule = [{'genes': f['genes'], 'year': f['origin']} for f in fs]
        matches=[]
        for row in db.execute('SELECT cache_key,request FROM evaluations'):
            req=json.loads(row['request'])
            if (req.get('schedule')==schedule and req['capital']==100 and req['stress']=='nominal'
                and req['period']['fold']=='continuous_frozen_schedule' and not req['benchmark']):
                matches.append(row['cache_key'])
        if len(matches)!=1:raise ValueError('ambiguous_reference')
        row=db.execute('SELECT * FROM evaluations WHERE cache_key=?', (matches[0],)).fetchone()
        book={k:json.loads(gzip.decompress(row[k])) if k in ('daily','episodes','orders') else json.loads(row[k])
              for k in ('request','metrics','daily','episodes','orders','folds')}
        references[family]={'identity': ident, 'cache_key': matches[0], 'schedule': schedule,
                            **summarize(book), 'regime_annual_reset_diagnostics': [r for r in read_csv('regime_attribution','raw') if selected(r,ident)],
                            'stresses': [r for r in read_csv('continuous_stresses_neighbors') if selected(r,ident)]}
    db.close()
    calls=json.loads((DELIVERY/'raw/deepseek_proposals.json').read_text())
    lineage=json.loads((DELIVERY/'raw/mutation_lineage.json').read_text())
    genes=json.loads((DELIVERY/'raw/candidate_genes.json').read_text())
    groups=defaultdict(list)
    for row in genes:groups[json.dumps(effective_genes(row['genes']),sort_keys=True)].append(row['id'])
    duplicates=[ids for ids in groups.values() if len(ids)>1]
    dev=read_csv('development','raw'); comparisons=[]
    for child in lineage:
        if child['source'] != 'deepseek':continue
        current=[r for r in dev if r['run']==child['run'] and r['id']==child['candidate'] and int(r['generation'])==child['generation']]
        parent=[r for r in dev if r['run']==child['run'] and r['id']==child['parent'] and int(r['generation'])<child['generation']]
        if not current or not parent:continue
        p=max(parent,key=lambda r:int(r['generation']));c=current[0]
        delta={k:float(c[k])-float(p[k]) for k in ('validation_cagr','validation_mdd','validation_calmar')}
        signs=[delta['validation_cagr'], -delta['validation_mdd'], delta['validation_calmar']]
        label='tradeoff'
        if all(abs(v)<1e-12 for v in signs):label='equal'
        elif all(v>=-1e-12 for v in signs):label='improved_three_metrics'
        elif all(v<=1e-12 for v in signs):label='worsened_three_metrics'
        comparisons.append({'run':child['run'],'child':child['candidate'],'parent':child['parent'], 'delta':delta,'label':label})
    rejected=Counter()
    for call in calls:
        validation=call.get('validation') or {}
        if isinstance(validation,str):validation=json.loads(validation)
        for item in validation.get('rejected',[]):rejected[item['reason']]+=1
    final=json.loads((DELIVERY/'raw/results.json').read_text())
    result={'evidence_kind':'POST_SEAL_FORENSICS_NO_REPLAY_NO_SELECTION', 'references':references,
            'old_database_hashes':before, 'verified_snapshot_files':len(manifest),
            'deepseek':{'old_calls':len(calls),'lineage_sources':dict(Counter(r['source'] for r in lineage)),
                        'invalid_reasons':dict(rejected),'parent_comparisons':comparisons,
                        'parent_comparison_counts':dict(Counter(r['label'] for r in comparisons)),
                        'arm_medians_descriptive_not_causal':read_csv('arms_descriptive_only')},
            'inactive_gene_equivalence':{'candidate_ids':len(genes),'effective_configs':len(groups),
                                         'duplicate_groups':duplicates},
            'phase2_evaluations':0,'phase2_api_calls':0,'new_nominees':[]}
    after={name:sha(snapshot/name) for name in before}
    if before != after:raise ValueError('immutable_input_changed')
    result['input_databases_unchanged']=True
    output.parent.mkdir(parents=True,exist_ok=True)
    with output.open('x') as f:json.dump(result,f,indent=2,allow_nan=False)
    print(json.dumps({'references':{k:{'top3_usd':v['top_three_pnl_usd'], 'peak':v['max_drawdown_peak_day']['date'], 'trough':v['max_drawdown_first_trough_day']['date']} for k,v in references.items()},
                      'deepseek_parent_counts':result['deepseek']['parent_comparison_counts'], 'duplicates':len(duplicates), 'output':str(output)}))


if __name__ == '__main__':
    p=argparse.ArgumentParser();p.add_argument('--snapshot',required=True,type=Path);p.add_argument('--out',required=True,type=Path)
    a=p.parse_args();analyze(a.snapshot,a.out)
