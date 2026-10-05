"""Fail-closed development partition and chronological fold contract."""
import json
from datetime import date, timedelta
from pathlib import Path

PATH = Path(__file__).resolve().parents[2] / 'source_of_truth' / 'phase2_v2_contract.json'

def load():
    value = json.loads(PATH.read_text(encoding='utf-8'))
    validate(value)
    return value

def allowed(day, contract):
    day = str(day)[:10]
    date.fromisoformat(day)
    if day >= contract['forward_2027']['start']:
        return False
    if day in contract.get('excluded_days', []):
        return False
    if any(a <= day <= b for a, b in contract['outer_oos']['intervals'] + contract['original_frozen_outer']):
        return False
    return any(a <= day <= b for a, b in contract['authorized_development'])

def validate_folds(folds, contract):
    if not folds:
        raise ValueError('no_frozen_validation_folds')
    previous = None
    for a, b in folds:
        start, end = date.fromisoformat(a), date.fromisoformat(b)
        if end < start or (previous and start != previous + timedelta(days=1)):
            raise ValueError('noncontiguous_chronological_folds')
        for i in range((end-start).days+1):
            if not allowed((start+timedelta(days=i)).isoformat(), contract):
                raise ValueError('locked_or_unauthorized_day')
        previous = end
    if not allowed((date.fromisoformat(folds[0][0])-timedelta(days=1)).isoformat(), contract):
        raise ValueError('unauthorized_initial_mark')

def validate(contract, *, activate=False):
    if any(contract[k] for k in ('orders_allowed', 'production_writes_allowed', 'promotion_allowed')):
        raise ValueError('research_authority_violation')
    if contract['outer_oos']['status'] != 'LOCKED' or contract['outer_oos']['access_by_runner']:
        raise ValueError('outer_lock_violation')
    if contract['forward_2027']['status'] != 'SEALED' or contract['forward_2027']['access_by_runner']:
        raise ValueError('forward_seal_violation')
    for a, b in contract['authorized_development']:
        if b < a or b >= contract['forward_2027']['start']:
            raise ValueError('invalid_development_range')
        if any(a <= y and x <= b for x, y in contract['outer_oos']['intervals'] + contract['original_frozen_outer']):
            raise ValueError('development_overlaps_outer')
    validate_folds(contract['diagnostic_only_folds'], contract)
    if activate:
        if contract['activation_status'] != 'READY':
            raise ValueError(contract['activation_status'])
        folds = contract['walk_forward']['validation_folds']
        validate_folds(folds, contract)
        if [folds[0][0], folds[-1][1]] != contract['requested_development']:
            raise ValueError('requested_development_coverage_incomplete')
        if folds[-1][1] > contract['available_frozen_input_end']:
            raise ValueError('missing_frozen_input_coverage')
    return True

if __name__ == '__main__':
    c = load()
    print('CONTRACT_VALID=true; ACTIVATION=' + c['activation_status'])
