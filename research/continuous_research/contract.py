import json
from datetime import date
from pathlib import Path
from research.phase2_v2.contract import load as phase2, validate_folds

PATH=Path(__file__).resolve().parents[2]/'source_of_truth/continuous_research_contract_v1.json'


def validate(c):
    old=phase2()
    if any(c[k] for k in ('orders_allowed','production_writes_allowed','promotion_allowed')):
        raise ValueError('authority_violation')
    if c['development']!=old['authorized_development'][0] or c['sealed']!=old['outer_oos']['intervals'][0]:
        raise ValueError('partition_changed')
    for name in ('training','validation','diagnostic'):validate_folds([c[name]],old)
    for first,second in (('training','validation'),('validation','diagnostic')):
        if (date.fromisoformat(c[second][0])-date.fromisoformat(c[first][1])).days<=c['purge_days']:
            raise ValueError('purge_violation')
    if c['feedback_cutoff']!=c['validation'][1] or c['legacy_alpha_index']!=1444:raise ValueError('feedback_or_debt_reset')
    a=c['api'];s=c['scheduler']
    expected={'attempts_per_day':24,'input_tokens_per_request':6500,'output_tokens_per_request':1500,'usd_per_day':.25,'usd_per_month':5.}
    if any(a[k]!=v for k,v in expected.items()):raise ValueError('unauthorized_API_budget')
    if a['budget_id']!='continuous_research_shared_v1' or a['budget_timezone']!='Europe/Paris':raise ValueError('accounting_identity')
    if s['lifetime_batch_limit'] is not None or s['lifetime_pool_limit'] is not None:raise ValueError('scheduler_truncated')
    if s['batch_size']!=4 or s['candidates_per_activation']!=1 or s['candidate_starts_per_day']!=128:raise ValueError('operating_budget')
    if c['statistics']['block_days']!=30 or c['statistics']['gap_days']<14 or c['statistics']['min_nonzero_blocks']<30:raise ValueError('statistics_weakened')
    return c


def load():return validate(json.loads(PATH.read_text()))


if __name__=='__main__':print(json.dumps({'valid':True,'id':load()['id'],'lifetime_batch_limit':None}))
