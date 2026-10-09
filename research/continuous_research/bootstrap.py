"""One read-only import of global legacy registries and eligible feedback only."""
import json
import sqlite3
import itertools
from pathlib import Path
from .common import digest
from .contract import load
from .schema import spaces


def metrics(value):
    if not value:return None
    return {k:value.get(k) for k in ('cagr','mdd','log_growth','cost_drag','asset_concentration','turnover')}


def build():
    from research.anomaly_lab.rules import catalogue
    from research.discovery_evolution.runtime import audit
    c=load();old=Path(c['predecessor_release']);root=Path(c['predecessor_state'])
    boot=json.loads((old/'bootstrap.json').read_text());a=audit(root)
    if a['state']!='IDLE_NO_NEW_WORK' or a['conservative_lifetime_alpha_index']!=c['legacy_alpha_index']:
        raise ValueError('predecessor_checkpoint_changed')
    db=sqlite3.connect('file:'+(root/'research.sqlite').as_posix()+'?mode=ro',uri=True);db.execute('BEGIN')
    try:
        candidates={r[0]:json.loads(r[1]) for r in db.execute('SELECT id,body FROM candidates')}
        seen=set(boot['seen_gene_ids'])|set(candidates)
        parents=[]
        for gid,body in db.execute('SELECT candidate,body FROM feedback ORDER BY candidate'):
            r=json.loads(body);p=candidates[gid]
            parents.append({'id':gid,'genes':p['genes'],'rule':p['hypothesis']['rule'],
                'training':{'valid':r['training']['valid'],'metrics':metrics(r['training']['metrics']),
                            'interval':['2020-01-01','2021-12-17']},'validation':None,
                'frequency_episodes':r['discovery_episodes'],'cutoff':c['feedback_cutoff'],'source':'frozen_successor_training_only'})
        discovered=[json.loads(r[0]) for r in db.execute('SELECT body FROM discoveries')]
        configurations=[{'rule':v['hypothesis']['rule'],'genes':v['genes']} for v in candidates.values()]
    finally:db.rollback();db.close()
    space=spaces()[0];keys=list(space)
    all_k=[digest({'family':'K',**dict(zip(keys,v))}) for v in itertools.product(*(space[k] for k in keys))]
    return {'contract':digest(c),'seen_genes':sorted(seen),'configuration_hypotheses':configurations,
            'K_cardinality':len(all_k),'historical_K_count':len(set(all_k)&seen),
            'known_rules':catalogue(),'prior_training':parents,'cached_discoveries':discovered,
            'inherited':{'alpha_index':a['conservative_lifetime_alpha_index'],'legacy_lab':a['inherited'],
                         'historical_gene_count':len(seen),'successor_completed_candidates':len(candidates),
                         'successor_backtest_computations':a['backtest_calculations_completed'],
                         'successor_hash':a['last_event_hash'],'histories':boot['histories']},
            'scope':'prior_train_only; no diagnostic/outer metrics imported for selection'}
