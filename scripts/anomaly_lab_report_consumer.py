"""Read-only result consumer; frozen experiment and source books stay immutable."""
import argparse
import copy
import json
import os
from pathlib import Path
import sys


def validate(c):
    if c['experiment_or_evaluator_changes_allowed'] or c['orders_allowed'] or c['minimum_events_for_uncertainty'] < 20:
        raise ValueError('report_contract_violation')
    return c


def normalize(source, c):
    validate(c); result = copy.deepcopy(source)
    for sample in result['samples']:
        frequency = sample['frequency']
        frequency['by_asset_semantics'] = c['frequency_by_asset']
        if frequency['independent_events'] < c['minimum_events_for_uncertainty']:
            frequency['frequency_annual_rate_ci95'] = None
            frequency['uncertainty_status'] = 'INSUFFICIENT_EVIDENCE'
        else: frequency['uncertainty_status'] = 'BLOCK_BOOTSTRAP_DEVELOPMENT_ESTIMATE'
        sample['confirmed_trading_candidate'] = False
    status = result.get('status') or {}
    result['portfolio_summary_current'] = status.get('processed_origins') == result['counts']['origins']
    if not result['portfolio_summary_current']: result['status'] = {'state': 'SUMMARY_PENDING'}
    if result['unknown_billing']: result['usd_upper_estimate'] = None
    result['billing_semantics'] = 'native usage; documented upper tariff estimate separate from invoice; unknown is null'
    result['reporting_contract'] = c['id']; result['orders_allowed'] = False
    return result


def main():
    p = argparse.ArgumentParser(); p.add_argument('--release', type=Path, required=True)
    p.add_argument('--root', type=Path, required=True); p.add_argument('--contract', type=Path, required=True)
    a = p.parse_args(); sys.path.insert(0, str(a.release))
    from research.anomaly_lab.audit import audit
    c = validate(json.loads(a.contract.read_text()))
    result = normalize(audit(a.root), c)
    out = a.root/'discovery_report.json'; temp = out.with_name(out.name+'.'+str(os.getpid())+'.tmp')
    temp.write_text(json.dumps(result, sort_keys=True, allow_nan=False)); os.replace(temp, out)
    print(json.dumps({'report': str(out), 'origins': result['counts']['origins'], 'hash_chain': result['hash_chain']}))


if __name__ == '__main__': main()
