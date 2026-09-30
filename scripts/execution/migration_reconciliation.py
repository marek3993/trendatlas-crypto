"""Classify existing execution evidence. No exchange or scheduler mutations."""


def classify_execution(manifest, payload, activation):
    journal = payload.get('journal', {}).get('tables', {})
    actions = journal.get('multi_account_execution_actions', [])
    accounts = payload.get('accounts', [])
    stages = manifest.get('stages', {})
    target = payload.get('target', {})
    terminal_accounts = {r.get('hyperliquid_account_id') for r in journal.get('multi_account_execution_runs', [])
                         if r.get('canonical_signal_id') == target.get('signalId')
                         and r.get('canonical_closed_day') == target.get('closedDay')
                         and r.get('status') in {'NO_ACTION', 'FILLED_AND_ALIGNED'} and r.get('completed_at')}
    verified = bool(
        activation.get('previous_run_id')
        and manifest.get('run_id') != activation['previous_run_id']
        and manifest.get('no_submit') is False
        and manifest.get('target_closed_day') == payload.get('target', {}).get('closedDay')
        and manifest.get('signal_id') == payload.get('target', {}).get('signalId')
        and manifest.get('execution_outcome') in {'NO_ACTION', 'FILLED_AND_ALIGNED'}
        and manifest.get('final_status') in {'SUCCESS', 'EXECUTION_COMPLETE_PUBLISH_FAILED'}
        and all(stages.get(s, {}).get('status') == 'PASSED' for s in ('EXECUTE', 'POST_TRADE_VERIFY'))
        and payload.get('journalUnchanged') is True
        and {'multi_account_execution_runs','multi_account_execution_actions','multi_account_agent_nonces','multi_account_execution_locks'}.issubset(journal)
        and not journal.get('multi_account_execution_locks')
        and all(a.get('verification_state') == 'VERIFIED' for a in actions)
        and accounts and all(a.get('plan', {}).get('state') == 'NO_ACTION' and a.get('accountId') in terminal_accounts for a in accounts)
    )
    published = verified and manifest.get('final_status') == 'SUCCESS' and manifest.get('authority_status') == 'PASSED'
    return {'execution_verified': verified, 'publication_verified': published, 'verified': published,
            'reason_code': 'VERIFIED' if published else 'PUBLICATION_PENDING' if verified else 'SUBMISSION_UNRESOLVED'}
