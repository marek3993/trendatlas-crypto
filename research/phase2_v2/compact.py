"""Bounded proposal context; historical candidate deduplication stays in SQLite."""
import json
import itertools
from pathlib import Path

from .market import canonical, digest, mutate

POLICY = json.loads((Path(__file__).resolve().parents[2] / 'source_of_truth' / 'phase2_broker_policy.json').read_text())


def rounded(value):
    if isinstance(value, float):
        return round(value, 6)
    if isinstance(value, dict):
        return {k: rounded(v) for k, v in value.items()}
    if isinstance(value, list):
        return [rounded(v) for v in value]
    return value


def compact_parent(parent):
    fields = ('cagr', 'mdd', 'sharpe', 'calmar', 'cost_drag', 'asset_concentration',
              'trade_concentration', 'no_best_day_cagr', 'no_top3_trades_cagr',
              'double_cost_cagr', 'delayed_entry_cagr', 'worst_fold_return',
              'profitable_fold_fraction', 'parameter_stability', 'turnover')
    folds = sorted(parent.get('folds', []), key=lambda f: f.get('metrics', {}).get('net_return', 0))
    return rounded({'id': parent['id'], 'genes': parent['genes'],
                    'eligible': parent.get('eligible', False), 'reasons': parent.get('reasons', []),
                    'metrics': {k: parent.get('metrics', {}).get(k) for k in fields},
                    'weak_folds': [{'start': f['start'], 'end': f['end'],
                                    'metrics': {k: f.get('metrics', {}).get(k) for k in
                                                ('net_return', 'mdd', 'cost_drag', 'trade_concentration')}}
                                   for f in folds[:POLICY['weak_folds_per_parent_max']]]})


def wire_payload(payload):
    """Also sanitize queued legacy requests without changing their mailbox binding."""
    parents = []
    for p in payload['parents'][:POLICY['parents_max']]:
        parents.append(p if 'weak_folds' in p else compact_parent(p))
    return {k: v for k, v in {
        'family': payload['family'], 'parents': parents, 'schema': payload['schema'],
        'aggregate': payload.get('aggregate'),
        'unseen_options': payload.get('unseen_options', [])[:POLICY['unseen_options_max']],
        'scope': payload['scope'], 'excluded': 'outer_oos_and_forward_2027',
        'requested_mutations': POLICY['mutations_per_request'],
    }.items() if v is not None}
