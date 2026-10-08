"""Validate the authorized source contract before any consumer runs."""
import hashlib
import json
from pathlib import Path
from research.phase2_v2.contract import load as phase2_contract, validate_folds

PATH = Path(__file__).resolve().parents[2] / 'source_of_truth/anomaly_lab_contract.json'


def load():
    c = json.loads(PATH.read_text(encoding='utf-8'))
    p = phase2_contract()
    if any(c[k] for k in ('orders_allowed', 'production_writes_allowed', 'promotion_allowed')):
        raise ValueError('lab_authority_violation')
    if c['development'] != p['authorized_development'][0] or c['sealed'] != p['outer_oos']['intervals'][0]:
        raise ValueError('partition_mismatch')
    if c['excluded'] != p['excluded_days'] or c['training']['purge_days'] < max(c['horizons']):
        raise ValueError('purge_or_exclusion_mismatch')
    if c['budgets']['max_hypotheses'] != sum(len(v['threshold']) * len(c['horizons']) for v in c['families'].values()):
        raise ValueError('unfrozen_search_cardinality')
    if c['budgets']['max_origins'] != len(p['walk_forward']['validation_folds']):
        raise ValueError('unfrozen_origins')
    validate_folds(p['walk_forward']['validation_folds'], p)
    if c['exposure'] > p['execution']['maximum_gross'] or c['historical_independence'].startswith('NONE') is False:
        raise ValueError('exposure_or_independence')
    engine = Path(__file__).resolve().parents[1] / 'phase2_v2/engine.py'
    if hashlib.sha256(engine.read_text().encode()).hexdigest() != c['engine_normalized_sha256']:
        raise ValueError('frozen_engine_changed')
    return c


if __name__ == '__main__':
    c = load()
    print(json.dumps({'contract': c['id'], 'valid': True, 'orders_allowed': False,
                      'development': c['development'], 'sealed_access': False}))
