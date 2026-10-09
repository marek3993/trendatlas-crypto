import json
from datetime import date
from pathlib import Path
from research.phase2_v2.contract import load as phase2, validate_folds
from research.anomaly_lab.contract import load as predecessor

PATH = Path(__file__).resolve().parents[2]/'source_of_truth/discovery_evolution_contract_v2.json'


def validate(c):
    p = phase2(); old = predecessor()
    if any(c[k] for k in ('orders_allowed', 'production_writes_allowed', 'promotion_allowed')):
        raise ValueError('authority_violation')
    if c['development'] != p['authorized_development'][0] or c['sealed'] != p['outer_oos']['intervals'][0]:
        raise ValueError('partition_changed')
    if c['legacy_alpha_debt'] != 1428 or c['new_api_calls_allowed'] != 0:
        raise ValueError('debt_or_api_reset')
    if c['api_limits'] != {'calls': old['budgets']['api_calls_lifetime_max'], 'tokens': old['budgets']['api_tokens_lifetime_max'], 'usd_upper': old['budgets']['api_usd_upper_lifetime_max']}:
        raise ValueError('api_limits_changed')
    validate_folds([c['training']], p); validate_folds([c['test']], p)
    if (date.fromisoformat(c['test'][0])-date.fromisoformat(c['training'][1])).days <= c['purge_days']:
        raise ValueError('purge_violation')
    s = c['statistics']; b = c['budgets']
    if s['gap_days'] < 14 or s['block_days'] < 30 or s['min_nonzero_blocks'] < 30:
        raise ValueError('dependence_requirements_weakened')
    days = (date.fromisoformat(c['test'][1])-date.fromisoformat(c['test'][0])).days+1
    n = (days+s['gap_days'])//(s['block_days']+s['gap_days'])
    end_t = c['legacy_alpha_debt']+b['pool_max']
    if n < s['min_nonzero_blocks'] or 2.**(-s['min_nonzero_blocks']) > .05/(end_t*(end_t+1)):
        raise ValueError('statistical_design_infeasible')
    if b['pool_max'] != b['batch_size']*b['cycles_max'] or b['candidates_per_activation'] != 1:
        raise ValueError('unfrozen_budget')
    return c


def load(): return validate(json.loads(PATH.read_text()))


if __name__ == '__main__':
    c = load(); print(json.dumps({'valid': True, 'contract': c['id'], 'new_api_calls_allowed': 0}))
