"""Read-only admission: a new name never bypasses the sealed refit contract."""
import datetime as dt
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
CONTRACT = json.loads((HERE / 'contract.json').read_text())


def check(today, evidence):
    a = CONTRACT['admission']
    reasons = []
    if today < dt.date.fromisoformat(a['not_before']):
        reasons.append('fixed_refit_not_due')
    cutoff = dt.date.fromisoformat(evidence.get('closed_through', '2025-12-31'))
    if cutoff >= today:
        reasons.append('unclosed_UTC_day')
    if (cutoff - dt.date.fromisoformat(a['new_days_anchor'])).days < a['minimum_new_closed_days']:
        reasons.append('fewer_than_30_new_closed_days')
    if cutoff < dt.date(a['new_complete_year'], 12, 31):
        reasons.append('no_new_complete_annual_outer_window')
    for key in ('append_only_verified', 'complete_pit_coverage', 'source_hashes_verified'):
        if evidence.get(key) is not True:
            reasons.append(key + '_missing')
    if not a['implementation_ready']:
        reasons.append('research_engine_and_event_overlap_validation_not_ready')
    return {'verdict': 'BLOCKED_WITHOUT_STATE_CHANGE' if reasons else 'ELIGIBLE_FOR_REVIEW',
            'reasons': reasons, 'not_before': a['not_before'],
            'evaluations': 0, 'api_calls': 0, 'forward_nominees': []}


if __name__ == '__main__':
    print(json.dumps(check(dt.datetime.now(dt.timezone.utc).date(), {}), indent=2))
