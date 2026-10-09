"""Freeze globally novel genes and prior-cutoff outbox lineage before any results."""
import itertools
import json
import sqlite3
from collections import defaultdict
from pathlib import Path
from research.phase2_v2.market import SPACE, digest, validate_genes
from research.anomaly_lab.rules import validate
from .contract import load


def novel_k(root, rule, seen):
    """Bridge inside existing authorized K schema, not an equivalent anomaly rule."""
    preferred = {'trend_days': root.get('slow_days', root.get('market_sma_days', 150)),
                 'vol_days': 30 if 'vol' in rule['family'] else 20,
                 'vol_target': root.get('vol_target', .1), 'correlation_cap': .5,
                 'asset_weight_cap': .1 if rule['action'] != 'long' else .15, 'rebalance_days': rule['horizon']}
    keys = list(SPACE['K'])
    choices = [sorted(SPACE['K'][k], key=lambda v: (abs(v-preferred[k]), v)) for k in keys]
    for values in itertools.product(*choices):
        genes = {'family': 'K', **dict(zip(keys, values))}
        if digest(genes) not in seen: return validate_genes(genes)
    return None


def build_pool(receipts, seen, c=None):
    c = c or load(); roots = {}
    for r in receipts:
        validate(r['rule']); validate_genes(r['genes'])
        if r['training_cutoff'] > c['training'][1]: continue
        prior = roots.get(r['hypothesis_id'])
        if prior is None or r['training_cutoff'] > prior['training_cutoff']: roots[r['hypothesis_id']] = r
    groups = defaultdict(list)
    for r in sorted(roots.values(), key=lambda r: r['hypothesis_id']): groups[r['rule']['family']].append(r)
    ordered = [r for row in itertools.zip_longest(*(groups[k] for k in sorted(groups))) for r in row if r]
    used = set(seen); pool = []
    for r in ordered:
        genes = novel_k(r['genes'], r['rule'], used)
        if genes is None: break
        gid = digest(genes); used.add(gid)
        hypothesis = {'version': c['discovery']['version'], 'rule': r['rule'], 'training': c['training']}
        pool.append({'hypothesis_id': digest(hypothesis), 'hypothesis': hypothesis, 'genes': genes, 'gene_id': gid,
                     'root_receipt': r['receipt_id'], 'root_hypothesis': r['hypothesis_id'], 'root_genes': r['genes'],
                     'root_cutoff': r['training_cutoff'], 'mapping': c['evolution']['family_bridge']})
        if len(pool) == c['budgets']['pool_max']: break
    return pool


def bootstrap():
    c = load(); old_root = Path(c['legacy_lab'])
    db = sqlite3.connect('file:'+str(old_root/'lab.sqlite')+'?mode=ro', uri=True); db.execute('BEGIN')
    try:
        receipts = []; inference = []
        for body, in db.execute('SELECT body FROM handoffs'):
            r = json.loads(body); expected = r.pop('content_hash')
            if digest(r) != expected or r['orders_allowed'] or r['confirmed_trading_candidate']: raise ValueError('unsafe_legacy_receipt')
            receipts.append({'receipt_id': r['id'], 'hypothesis_id': r['hypothesis_id'], 'rule': r['hypothesis']['rule'],
                             'genes': r['phase2_gene_proposal'], 'training_cutoff': r['training_cutoff'], 'source_hash': expected})
        for table in ('results', 'books'):
            for body, in db.execute('SELECT body FROM '+table):
                r = json.loads(body)
                if 'discovery' in r: inference.append(r['discovery']['inference'])
        usage = [json.loads(r[0])['response'].get('usage', {}) for r in db.execute('SELECT body FROM ai_receipts')]
        inherited = {'backtest_trials': db.execute('SELECT COUNT(*) FROM trials').fetchone()[0],
                     'hypotheses': db.execute('SELECT COUNT(*) FROM hypotheses').fetchone()[0],
                     'handoffs': len(receipts), 'api_calls': sum(r.get('api_call', 0) for r in usage),
                     'api_tokens': sum(r.get('total_tokens') or 0 for r in usage),
                     'api_unknown_billing': any(r.get('uncertain') for r in usage),
                     'last_event_hash': db.execute('SELECT hash FROM events ORDER BY id DESC LIMIT 1').fetchone()[0],
                     'statistic_calls': len(inference), 'nonnull_pvalues': sum(r['p'] is not None for r in inference),
                     'nonnull_resolution_exceeds_alpha': sum(r['p'] is not None and 2.**(-r['blocks']) > r['alpha'] for r in inference)}
    finally: db.rollback(); db.close()
    if inherited['backtest_trials'] != c['legacy_alpha_debt'] or inherited['api_calls'] != c['api_limits']['calls']:
        raise ValueError('legacy_checkpoint_or_budget_changed')
    seen = set(); histories = []
    for path in ('/var/lib/trendatlas-research-development/research.sqlite', '/var/lib/trendatlas-research-v2/v2.sqlite'):
        db = sqlite3.connect('file:'+path+'?mode=ro', uri=True); db.execute('BEGIN')
        try:
            rows = db.execute('SELECT genes FROM candidates').fetchall()
            ids = sorted(digest(validate_genes(json.loads(g))) for g, in rows); seen.update(ids)
            histories.append({'path': path, 'registered_candidates': len(rows), 'normalized_gene_ids_digest': digest(ids),
                              'backtest_evaluations': db.execute('SELECT COUNT(*) FROM evaluations').fetchone()[0]})
        finally: db.rollback(); db.close()
    pool = build_pool(receipts, seen, c)
    return {'contract': digest(c), 'inherited': inherited, 'histories': histories, 'seen_gene_ids': sorted(seen),
            'legacy_receipts': receipts, 'pool': pool, 'pool_digest': digest(pool), 'frozen_before_new_results': True}
