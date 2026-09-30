"""Bind operator readiness to a current observation without freezing market prices."""
from datetime import datetime, timedelta, timezone
import hashlib
import json
from scripts.execution.migration_diagnostics import MigrationError


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def bindings(payload):
    accounts = []
    for row in payload['accounts']:
        account = row['account']
        accounts.append({'identity': [row['accountId'], row['masterAddress'].lower(), row['signerFingerprint']],
                         'positions': sorted([{'asset': p['asset'], 'size': p['size']} for p in account['positions']], key=digest),
                         'open_orders': sorted(account['openOrders'], key=digest),
                         'open_order_count': account['openOrderCount'],
                         'recent_fills': sorted(row['recentFills'], key=digest)})
    return {'closed_day': payload['target']['closedDay'], 'target_sha256': digest(payload['target']),
            'account_sha256': digest(sorted(accounts, key=digest)),
            'journal_sha256': payload['journal']['sha256'],
            'planner_sha256': digest(sorted([{'account_id': a['accountId'], 'plan': a['plan']} for a in payload['accounts']], key=digest))}


def validate_receipt(ready, payload, now=None, *, runtime_inputs_sha256=None):
    now = now or datetime.now(timezone.utc)
    if ready.get('receipt_version') != 2:
        raise MigrationError('RECEIPT_UNBOUND')
    expected = (now.date() - timedelta(days=1)).isoformat()
    if ready.get('closed_day') != expected or payload['target']['closedDay'] != expected:
        raise MigrationError('RECEIPT_DAY_CHANGED')
    try:
        age = (now - datetime.fromisoformat(ready['observed_at'])).total_seconds()
    except (KeyError, ValueError, TypeError):
        raise MigrationError('RECEIPT_EXPIRED') from None
    if not 0 <= age < 3600:
        raise MigrationError('RECEIPT_EXPIRED')
    if runtime_inputs_sha256 is not None and ready.get('runtime_inputs_sha256') != runtime_inputs_sha256:
        raise MigrationError('RECEIPT_INPUTS_CHANGED')
    current = bindings(payload)
    for key, code in [('target_sha256', 'RECEIPT_TARGET_CHANGED'), ('account_sha256', 'RECEIPT_ACCOUNT_CHANGED'),
                      ('journal_sha256', 'RECEIPT_JOURNAL_CHANGED'), ('planner_sha256', 'RECEIPT_PLANNER_CHANGED')]:
        if ready.get(key) != current[key]:
            raise MigrationError(code)
    replay = ready.get('current_replay', {})
    if (replay.get('status') != 'PASS' or replay.get('closed_day') != expected
            or replay.get('target_sha256') != current['target_sha256']
            or replay.get('account_sha256') != current['account_sha256']
            or not replay.get('report_sha256') or not replay.get('inputs_sha256')):
        raise MigrationError('REPLAY_UNBOUND')
