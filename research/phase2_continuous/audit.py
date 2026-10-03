"""Read-only, credential-free snapshot of development progress and API evidence."""
import argparse
import collections
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


def snapshot(root, original=None):
    root = Path(root)
    db = sqlite3.connect('file:' + (root / 'research.sqlite').as_posix() + '?mode=ro', uri=True)
    db.execute('BEGIN')
    cycle = db.execute('SELECT * FROM cycles ORDER BY ordinal DESC LIMIT 1').fetchone()
    candidates = {r[0]: r[1:] for r in db.execute('SELECT id,cycle_id,family,generation,mutation FROM candidates')}
    counts = dict(db.execute('SELECT status,COUNT(*) FROM evaluations GROUP BY status'))
    result = {'utc': datetime.now(timezone.utc).isoformat(), 'cycle': cycle,
              'active_evolution': bool(cycle and cycle[2] == 'ACTIVE'), 'evaluations': counts,
              'last_evaluation_utc': db.execute("SELECT MAX(finished) FROM evaluations WHERE status='COMPLETE'").fetchone()[0],
              'checkpoint_utc': datetime.fromtimestamp((root / 'status.json').stat().st_mtime, timezone.utc).isoformat(),
              'families': dict(db.execute('SELECT family,COUNT(*) FROM candidates GROUP BY family')),
              'candidate_count': len(candidates),
              'fully_completed_candidates': db.execute("SELECT COUNT(*) FROM (SELECT candidate_id FROM evaluations GROUP BY candidate_id HAVING COUNT(*)=16 AND SUM(status='COMPLETE')=16)").fetchone()[0],
              'cycle_evaluations': dict(db.execute('SELECT e.status,COUNT(*) FROM evaluations e JOIN candidates c ON c.id=e.candidate_id WHERE c.cycle_id=? GROUP BY e.status', (cycle[0],))),
              'family_stages': list(db.execute('SELECT family,generation,state,request_hash FROM family_stage WHERE cycle_id=?', (cycle[0],))),
              'evaluation_duplicate_keys': db.execute('SELECT COUNT(*)-COUNT(DISTINCT key) FROM evaluations').fetchone()[0],
              'sqlite_quick_check': db.execute('PRAGMA quick_check').fetchone()[0],
              'foreign_key_errors': db.execute('PRAGMA foreign_key_check').fetchall(),
              'ledger_bytes': (root / 'research.sqlite').stat().st_size}
    # Measure the same nominal development metrics for each lineage, without reopening OOS.
    result['lineage_quality'] = list(db.execute("""
      SELECT CASE WHEN c.mutation LIKE 'deepseek:%' THEN 'deepseek'
                  WHEN c.generation=0 THEN 'initial' ELSE 'deterministic' END,
             COUNT(DISTINCT c.id), AVG(json_extract(e.result,'$.cagr')),
             AVG(json_extract(e.result,'$.mdd')), AVG(json_extract(e.result,'$.cost_drag')),
             AVG(json_extract(e.result,'$.net_return')>0)
      FROM evaluations e JOIN candidates c ON c.id=e.candidate_id
      WHERE e.status='COMPLETE' AND e.stress='nominal' GROUP BY 1"""))
    db.close()
    totals = collections.Counter(); daily = collections.defaultdict(collections.Counter)
    errors = collections.Counter(); proposal_counts = collections.Counter(); success = []
    pending = 0; transport_attempts = 0; duplicate_provider_ids = 0; provider_ids = set()
    requests = root / 'mailbox' / 'requests'; responses = root / 'mailbox' / 'responses'
    for p in requests.glob('*.json'):
        path = responses / p.name
        if not path.exists():
            pending += 1
            continue
        r = json.loads(path.read_text()); u = r.get('usage') or {}
        for k in ('api_call', 'total_tokens', 'input_cache_hit_tokens', 'input_cache_miss_tokens', 'output_tokens', 'usd_upper_estimate'):
            totals[k] += u.get(k) or 0
        daily[r['utc'][:10]]['calls'] += u.get('api_call') or 0
        daily[r['utc'][:10]]['tokens'] += u.get('total_tokens') or 0
        errors[str(r.get('error'))] += 1
        transport_attempts += len(r.get('attempts', [])) if r.get('attempts') else u.get('api_call', 0)
        if u.get('uncertain'):
            totals['unknown_billing_calls'] += 1
        pid = u.get('provider_request_id')
        if pid:
            duplicate_provider_ids += int(pid in provider_ids); provider_ids.add(pid)
        if r.get('state') != 'COMPLETE' or not u.get('api_call'):
            continue
        request = json.loads(p.read_text()); payload = request['payload']
        payload_bytes = len(canonical(payload).encode())
        success.append({'utc': r['utc'], 'hash': p.stem, 'wire_hash': r.get('wire_hash'),
                        'usage': u, 'payload_bytes': payload_bytes,
                        'seen_bytes': len(canonical(payload.get('seen', [])).encode()),
                        'input_token_upper_bound': r.get('input_token_upper_bound'), 'model': r.get('model')})
        accepted = 0
        try:
            rows = json.loads(r['content'])['candidates']; proposal_counts['returned_candidates'] += len(rows)
            local_seen = set()
            for row in rows:
                cid = hashlib.sha256(canonical(row['genes']).encode()).hexdigest()
                registered = candidates.get(cid)
                if cid not in local_seen and registered and registered[0] == payload['cycle_id'] and registered[3].startswith('deepseek:'):
                    accepted += 1
                local_seen.add(cid)
        except (ValueError, KeyError, TypeError):
            proposal_counts['invalid_envelopes'] += 1
        proposal_counts['calls_with_accepted_mutation'] += int(accepted > 0)
        proposal_counts['calls_with_four_accepted_mutations'] += int(accepted == 4)
        proposal_counts['accepted_unique_candidates'] += accepted
        proposal_counts['calls_with_no_accepted_mutation'] += int(accepted == 0)
    success.sort(key=lambda r: r['utc'])
    result.update(api_totals=dict(totals), api_daily=dict(daily), api_errors=dict(errors),
                  api_avg_tokens=totals['total_tokens'] / totals['api_call'] if totals['api_call'] else None,
                  api_max_call=max(success, key=lambda r: r['usage']['total_tokens']) if success else None,
                  api_last_call=success[-1] if success else None, api_last_five=success[-5:],
                  proposal_quality=dict(proposal_counts), pending_requests=pending,
                  transport_attempts=transport_attempts, duplicate_provider_ids=duplicate_provider_ids)
    if original:
        old = json.loads(Path(original).read_text()); usage = collections.Counter()
        for r in old:
            u = r.get('usage') or {}
            for name, legacy in [('api_call', 'api_call'), ('total_tokens', 'total_tokens'),
                                 ('input_cache_hit_tokens', 'cache_hit_tokens'), ('input_cache_miss_tokens', 'cache_miss_tokens'),
                                 ('output_tokens', 'output_tokens'), ('usd_upper_estimate', 'usd')]:
                usage[name] += u.get(legacy) or 0
            usage['unknown_billing_calls'] += int(bool(u.get('uncertain')))
        result['predecessor_usage'] = dict(usage)
        result['combined_local_usage'] = {k: totals[k] + usage[k] for k in usage}
        result['dashboard_difference_at_supplied_snapshot'] = {'requests': 587 - totals['api_call'] - usage['api_call'],
                                                              'tokens': 10011394 - totals['total_tokens'] - usage['total_tokens']}
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', default='/var/lib/trendatlas-research-development')
    parser.add_argument('--original')
    args = parser.parse_args()
    print(canonical(snapshot(args.root, args.original)))
