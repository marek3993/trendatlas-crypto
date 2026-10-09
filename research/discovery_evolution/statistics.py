"""Exact finite-resolution block-sign inference; no Monte Carlo significance floor."""
import math
from datetime import date
import numpy as np
from .contract import load


def tail(k, n, probability=.5):
    return sum(math.comb(n, i)*probability**i*(1-probability)**(n-i) for i in range(k, n+1))


def design(c=None):
    c = c or load(); s = c['statistics']; t = c['legacy_alpha_debt']+c['budgets']['pool_max']
    days = (date.fromisoformat(c['test'][1])-date.fromisoformat(c['test'][0])).days+1
    n = (days+s['gap_days'])//(s['block_days']+s['gap_days']); alpha = .05/(t*(t+1))
    critical = next((k for k in range(n+1) if tail(k, n) <= alpha), None)
    return {'calendar_days': days, 'available_full_blocks': n, 'minimum_required_nonzero_blocks': s['min_nonzero_blocks'],
            'last_planned_alpha_index': t, 'worst_planned_alpha': alpha, 'minimum_p_at_required_blocks': 2.**(-s['min_nonzero_blocks']),
            'minimum_p_at_available_blocks': 2.**(-n), 'critical_positive_blocks_at_full_coverage': critical,
            'power_at_block_positive_probability': {str(p): tail(critical, n, p) if critical is not None else 0. for p in (.5, .55, .7, .8, .9, .95)},
            'feasible_in_principle': critical is not None, 'guaranteed_power_on_market_data': False,
            'assumption': s['null_assumption']}


def infer(candidate, reference, index, c=None):
    c = c or load(); s = c['statistics']; alpha = .05/(index*(index+1))
    if [r['date'] for r in candidate] != [r['date'] for r in reference]: raise ValueError('unaligned_paired_books')
    d = np.array([r['log_return']-b['log_return'] for r, b in zip(candidate, reference)])
    if not np.isfinite(d).all(): raise ValueError('nonfinite_endpoint')
    values = [float(d[i:i+s['block_days']].sum()) for i in range(0, len(d)-s['block_days']+1, s['block_days']+s['gap_days'])]
    nonzero = [v for v in values if abs(v) > 1e-12]; n = len(nonzero); positives = sum(v > 0 for v in nonzero)
    p = tail(positives, n) if n >= s['min_nonzero_blocks'] else None
    return {'endpoint': s['primary_endpoint'], 'alpha_index': index, 'alpha': alpha, 'full_blocks': len(values),
            'nonzero_blocks': n, 'positive_blocks': positives, 'minimum_attainable_p': 2.**(-n) if n else None,
            'p': p, 'rejected_under_declared_null': p is not None and p <= alpha,
            'verdict': 'INSUFFICIENT_EVIDENCE' if p is None else ('CONDITIONAL_DEVELOPMENT_ASSOCIATION' if p <= alpha else 'NO_ASSOCIATION'),
            'block_values': values, 'confirmed_trading_candidate': False, 'claim': s['claim']}
