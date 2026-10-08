"""Validated outbox for future Phase2 origins, without editing completed cycles."""
import argparse
import json
from pathlib import Path
from research.phase2_v2.market import canonical, digest, validate_genes, SPACE
from research.phase2_v2.contract import allowed, load as phase2_contract
from research.phase2_v2.runtime import atomic, utc
from .rules import validate, definition


def phase2_genes(rule):
    # Explicit mechanism-inspired suggestions, never an assertion of equivalence.
    if rule['family'] in ('breakout', 'vol_compression', 'vol_expansion', 'volume_reaction', 'stop_trail_context'):
        target = rule['threshold'] if rule['family'] == 'breakout' else 40
        days = min(SPACE['N']['breakout_days'], key=lambda x: abs(x-target))
        genes = {'family': 'N', 'breakout_days': days, 'atr_days': 20, 'initial_stop_atr': 2.0, 'trailing_stop_atr': 4.0, 'risk_per_entry': .005}
    elif rule['action'] in ('avoid', 'reduce'):
        genes = {'family': 'L', 'market_sma_days': 150, 'momentum_days': 30, 'breadth_on': .55, 'vol_target': .10, 'adverse_exposure_fraction': 0.0}
    else:
        genes = {'family': 'M', 'slow_days': 120, 'breakout_days': 40, 'momentum_days': 30, 'vol_target': .10}
    return validate_genes(genes)


def export(db, root, origin, hid, evidence):
    from .runtime import event
    rule = evidence['rule']; key = digest([origin, hid])
    row = db.execute('SELECT body FROM handoffs WHERE id=?', (key,)).fetchone()
    if row:
        # Recover an interrupted write after the SQLite commit.
        path = Path(root)/'handoff'/f'{key}.json'
        if not path.exists(): atomic(path, json.loads(row[0]))
        return
    row = db.execute('SELECT parent,source,narrative FROM hypotheses WHERE id=?', (hid,)).fetchone()
    result = {'id': key, 'hypothesis_id': hid, 'origin': origin, 'training_cutoff': evidence['training_cutoff'],
              'hypothesis': definition(rule), 'parents': [row[0]] if row[0] else [], 'source': row[1],
              'narrative': json.loads(row[2]), 'past_validation': evidence,
              'phase2_gene_proposal': phase2_genes(rule),
              'mapping': 'mechanism-inspired frozen J-N schema proposal; not equivalent to the anomaly rule',
              'consumer': 'future Phase2 prior-training ingress only; completed cycles immutable',
              'hypothesis_status': 'TESTABLE_DEVELOPMENT_HYPOTHESIS',
              'independent_evidence': False, 'confirmed_trading_candidate': False, 'orders_allowed': False}
    result['content_hash'] = digest(result)
    with db:
        db.execute('INSERT INTO handoffs VALUES(?,?,?)', (key, canonical(result), utc()))
        event(db, 'phase2_hypothesis_handoff', id=key, hypothesis=hid, origin=origin)
    atomic(Path(root)/'handoff'/f'{key}.json', result)


def ingest(outbox, origin_start):
    """Read-only adapter callable by a future Phase2 coordinator before selection."""
    c = phase2_contract()
    if not allowed(origin_start, c): raise ValueError('locked_phase2_origin')
    accepted = []; genes_seen = set()
    for path in sorted(Path(outbox).glob('*.json')):
        body = json.loads(path.read_text()); expected = body.pop('content_hash')
        if digest(body) != expected: raise ValueError('tampered_handoff')
        validate(body['hypothesis']['rule']); validate_genes(body['phase2_gene_proposal'])
        if body['orders_allowed'] or body['confirmed_trading_candidate'] or body['independent_evidence']:
            raise ValueError('handoff_authority_or_evidence_violation')
        if not allowed(body['training_cutoff'], c) or body['training_cutoff'] >= origin_start: continue
        gh = digest(body['phase2_gene_proposal'])
        if gh in genes_seen: continue
        genes_seen.add(gh); accepted.append(body)
    return accepted


if __name__ == '__main__':
    p = argparse.ArgumentParser(); p.add_argument('--outbox', type=Path, required=True); p.add_argument('--origin-start', required=True)
    a = p.parse_args(); rows = ingest(a.outbox, a.origin_start)
    print(canonical({'accepted_unique_genes': len(rows), 'genes': [r['phase2_gene_proposal'] for r in rows],
                     'read_only': True, 'completed_v2_cycle_modified': False}))
